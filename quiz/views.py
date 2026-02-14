import json
import re
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response 
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model, authenticate 
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from .models import UserAnswerLog
from django.utils import timezone
from django.db.models import Count, Q, Avg, Max, Case, When, FloatField

from .models import Question, KnowledgeConcept, KeywordAnalysis, TopicMedia, UserAnswerLog, Option, UserQuestionNote, ExamCutoff
from .serializers import QuestionSerializer, KnowledgeConceptSerializer, KeywordAnalysisSerializer
# Add these specific Postgres imports
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank, TrigramSimilarity


User = get_user_model() 

# --- 0. AUTH APIs (Login & Signup) ---
@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def signup_api(request):
    if request.method == 'GET':
        return Response({
            'message': 'Use POST with JSON: username, password, first_name, last_name, email, mobile (optional)',
            'example': 'POST /api/auth/signup/ with Content-Type: application/json'
        }, status=status.HTTP_200_OK)
    username = request.data.get('username')
    password = request.data.get('password')
    first_name = request.data.get('first_name', '').strip()
    last_name = request.data.get('last_name', '').strip()
    email = request.data.get('email', '').strip()
    mobile = request.data.get('mobile', '').strip()

    if not username or not password:
        return Response({'error': 'Please provide both username and password'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(username=username).exists():
        return Response({'error': 'Username already exists'}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(username=username, password=password)
    user.is_premium = False
    user.first_name = first_name
    user.last_name = last_name
    user.email = email or username  # fallback for email if empty
    user.phone_number = mobile or None
    user.save()

    token, _ = Token.objects.get_or_create(user=user)

    return Response({
        'token': token.key,
        'username': user.username,
        'is_premium': user.is_premium
    }, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profile_api(request):
    """Returns is_premium for the authenticated user (used by Flutter on startup)."""
    user = request.user
    return Response({'is_premium': getattr(user, 'is_premium', False)}, status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def login_api(request):
    if request.method == 'GET':
        return Response({
            'message': 'Use POST with JSON: {"username": "...", "password": "..."}',
            'example': 'POST /api/auth/login/ with Content-Type: application/json'
        }, status=status.HTTP_200_OK)
    username = request.data.get('username')
    password = request.data.get('password')
    
    user = authenticate(username=username, password=password)
    if not user:
        return Response({'error': 'Invalid Credentials'}, status=status.HTTP_401_UNAUTHORIZED)
    
    token, _ = Token.objects.get_or_create(user=user)
    
    return Response({
        'token': token.key, 
        'username': user.username,
        # This sends the TRUE status from the database to Flutter
        'is_premium': getattr(user, 'is_premium', False) 
    }, status=status.HTTP_200_OK)


# --- 1. API to Fetch a Concept (Wiki Popups) ---
class ConceptDetailView(APIView):
    def get(self, request, term):
        concept = get_object_or_404(KnowledgeConcept, term__iexact=term)
        serializer = KnowledgeConceptSerializer(concept)
        return Response(serializer.data)

# --- 2. API to Fetch Questions (Quiz & Search) ---
# quiz/views.py

# quiz/views.py

class QuestionList(generics.ListAPIView):
    serializer_class = QuestionSerializer

    def get_queryset(self):
        queryset = Question.objects.prefetch_related('options').all()
        
        # 1. EXAM FILTER
        if self.request.query_params.get('exam'):
            queryset = queryset.filter(exam_name=self.request.query_params.get('exam'))

        # 2. SUBJECT FILTER
        subject_param = self.request.query_params.get('subject')
        if subject_param:
            queryset = queryset.filter(
                Q(subject__iexact=subject_param) | 
                Q(tags__icontains=subject_param)
            )

        # 3. YEAR FILTER
        if self.request.query_params.get('year'):
            queryset = queryset.filter(year=self.request.query_params.get('year'))

        # 4. HYBRID SEARCH (Typos + Plurals + Context)
        search_query = self.request.query_params.get('search')
        if search_query:
            clean_query = search_query.strip()

            # A. Full Text Search (Handles Plurals: "Microorganisms" == "Microorganism")
            # We look in Text, Tags, and Options. 'english' config handles stemming.
            search_vector = (
                SearchVector('text', weight='A', config='english') +
                SearchVector('tags', weight='A', config='english') +
                SearchVector('options__text_content', weight='B', config='english')
            )
            search_rank = SearchRank(search_vector, SearchQuery(clean_query, config='english'))

            # B. Trigram Similarity (Handles Typos: "Goverrrnace" ~= "Governance")
            # We check similarity on the Question Text and Tags
            similarity = TrigramSimilarity('text', clean_query) + TrigramSimilarity('tags', clean_query)

            queryset = queryset.annotate(
                rank=search_rank,
                similarity=similarity
            ).filter(
                # Condition 1: High Quality Match (Grammar/Word Stem correct)
                Q(rank__gte=0.1) | 
                # Condition 2: Fuzzy Match (Typo correct) - 0.1 means 10% similar
                Q(similarity__gt=0.1)
            ).order_by('-rank', '-similarity').distinct() # Best matches first

        # 5. KEYWORD FILTER
        if self.request.query_params.get('keyword'):
            queryset = queryset.filter(keyword_analytics__keyword=self.request.query_params.get('keyword')).distinct()
            
        return queryset

# --- 3. API for the Truth Meter (Analysis Dashboard) ---
class KeywordAnalysisAPI(APIView):
    def get(self, request):
        data = KeywordAnalysis.objects.values('keyword').annotate(
            total_count=Count('id'),
            true_count=Count('id', filter=Q(is_true_usage=True)),
            false_count=Count('id', filter=Q(is_true_usage=False))
        )
        return Response(data)

# --- 4. GAME MODE API ---
# In quiz/views.py

class GameModeView(APIView):
    def get(self, request):
        # 1. Fetch 10 random items
        items = KeywordAnalysis.objects.all().order_by('?')[:10]
        game_cards = []
        
        for item in items:
            context_text = ""
            context_text = item.question.text
            statement_text = ""
            
            # --- LOGIC TO EXTRACT CONTEXT (Fixes empty context issue) ---
            # CASE A: Keyword is in the Question Text
            if f"{{{{T:{item.keyword}}}}}" in item.question.text or f"{{{{F:{item.keyword}}}}}" in item.question.text:
                lines = item.question.text.split('\n')
                for line in lines:
                    if f"{{{{T:{item.keyword}}}}}" in line or f"{{{{F:{item.keyword}}}}}" in line:
                        statement_text = line
                        break
                if not statement_text: statement_text = item.question.text
                context_text = item.question.text # <--- Set Context from Question

            # CASE B: Keyword is in an Option
            else:
                for opt in item.question.options.all():
                    if f"{{{{T:{item.keyword}}}}}" in opt.text_content or f"{{{{F:{item.keyword}}}}}" in opt.text_content:
                        statement_text = opt.text_content
                        context_text = item.question.text # <--- Set Context from Question
                        break
            
            # --- NEW: FETCH STATS FOR INSIGHT CARD ---
            # We calculate the global stats for this keyword to show "History says..."
            stats = KeywordAnalysis.objects.filter(keyword=item.keyword).aggregate(
                total=Count('id'),
                true_count=Count('id', filter=Q(is_true_usage=True)),
                false_count=Count('id', filter=Q(is_true_usage=False))
            )

            if statement_text:
                clean_statement = re.sub(r'\{\{[TF]:(.*?)\}\}', r'\1', statement_text)
                clean_context = re.sub(r'\{\{[TF]:(.*?)\}\}', r'\1', context_text)
                # 2. FIX: Remove Wiki Tags [[Word]] -> Word
                clean_statement = re.sub(r'\[\[(.*?)\]\]', r'\1', clean_statement)
                clean_context = re.sub(r'\[\[(.*?)\]\]', r'\1', clean_context) 
                
                game_cards.append({
                    "id": item.id, 
                    "keyword": item.keyword, 
                    "context": clean_context,   
                    "text": clean_statement, 
                    "is_true": item.is_true_usage,
                    "subject": item.question.subject, 
                    "year": item.question.year,
                    
                    # New Data for Feedback Card
                    "true_count": stats['true_count'],
                    "false_count": stats['false_count'],
                    "total_count": stats['total']
                })
                
        return Response(game_cards)

# --- 5. ANSWER LOGGING API (FIXED & UNIFIED) ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_user_answer(request):
    data = request.data
    try:
        # --- 1. GET OBJECTS (Safe Lookup) ---
        question = Question.objects.get(id=data['question_id'])
        
        selected_option = None
        if data.get('selected_option_id'):
            selected_option = Option.objects.get(id=data['selected_option_id'])

        # --- 2. PREPARE DATA (Preserving your logic) ---
        
        # Handle Eliminated Options (JSON or List)
        eliminated_raw = data.get('eliminated_options', '[]')
        if isinstance(eliminated_raw, str):
            try:
                eliminated_list = json.loads(eliminated_raw)
            except ValueError:
                eliminated_list = []
        else:
            eliminated_list = eliminated_raw

        # Handle Booleans
        is_skipped_val = str(data.get('is_skipped', 'false')).lower() == 'true'
        is_bookmarked_val = str(data.get('is_bookmarked', 'false')).lower() == 'true'
        is_correct_val = str(data.get('is_correct', 'false')).lower() == 'true'
        
        # Handle Confidence Score (Default to 100 if missing)
        try:
            confidence_val = int(float(data.get('confidence_score', 100)))
        except (ValueError, TypeError):
            confidence_val = 100

        # Handle Source Mode (Exam vs Practice)
        source_mode = data.get('source_mode', 'practice')
        session_id = data.get('session_id', None)

        # --- 3. BUILD THE DEFAULTS DICTIONARY ---
        # (This preserves ALL your original fields)
        defaults_data = {
            'selected_option': selected_option,
            'is_correct': is_correct_val,
            'is_skipped': is_skipped_val,
            'is_bookmarked': is_bookmarked_val,
            'time_taken_seconds': int(data.get('time_taken_seconds', 0)), 
            'confidence_score': confidence_val,
            'eliminated_options': eliminated_list,
            'source_mode': source_mode
        }

        # --- 4. THE FIX (Zombie Bookmark) ---
        # If user bookmarks this, we MUST make sure it is visible in the library
        if is_bookmarked_val:
            defaults_data['is_cleared_from_library'] = False

        # --- 5. SAVE TO DATABASE ---
        # We pass 'defaults_data' to 'defaults='
        # We use _, _ to ignore the output variables (Fixes unused variable warning)
        _, _ = UserAnswerLog.objects.update_or_create(
            user=request.user,
            question=question,
            session_id=session_id, 
            defaults=defaults_data 
        )

        return Response({"message": "State Updated"}, status=status.HTTP_200_OK)

    except Exception as e:
        print(f"ERROR SAVING ANSWER: {e}") 
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
# --- 6. TREND GRAPH API ---
class KeywordTrendAPI(APIView):
    def get(self, request):
        target_word = request.query_params.get('word')
        target_exam = request.query_params.get('exam')

        if not target_word:
            return Response({"error": "Please provide a 'word' parameter"}, status=400)

        keyword_qs = KeywordAnalysis.objects.filter(keyword__iexact=target_word)
        if target_exam: keyword_qs = keyword_qs.filter(exam_name=target_exam)

        if keyword_qs.exists():
            trend_data = keyword_qs.values('year').annotate(
                true_count=Count('id', filter=Q(is_true_usage=True)),
                false_count=Count('id', filter=Q(is_true_usage=False))
            ).order_by('year')
        else:
            question_qs = Question.objects.filter(
                Q(tags__icontains=target_word) | Q(text__icontains=target_word)
            )
            if target_exam: question_qs = question_qs.filter(exam_name=target_exam)
            
            trend_data = question_qs.values('year').annotate(
                true_count=Count('id'), 
                false_count=Count('id', filter=Q(pk__lt=0)) 
            ).order_by('year')

        video_url = None
        topic_media = TopicMedia.objects.filter(tag__iexact=target_word).first()
        if topic_media: video_url = topic_media.video_url

        return Response({
            "trend": list(trend_data),
            "video_url": video_url
        })
# --- 7. NOTE TAKING API ---

@api_view(['POST', 'GET'])
@permission_classes([IsAuthenticated])
def user_note_api(request):
    question_id = request.query_params.get('question_id') if request.method == 'GET' else request.data.get('question_id')
    if not question_id:
        return Response({"error": "Missing question_id"}, status=400)
    
    # NEW: Check for active bookmark
    has_active_bookmark = UserAnswerLog.objects.filter(
        user=request.user, question_id=question_id, is_bookmarked=True, is_cleared_from_library=False
    ).exists()
    if request.method == 'POST' and not has_active_bookmark:
        return Response({"error": "Cannot add note without bookmarking the question"}, status=400)
    
    if request.method == 'GET':
        try:
            note = UserQuestionNote.objects.get(user=request.user, question_id=question_id)
            return Response({"note": note.note_text}, status=200)
        except UserQuestionNote.DoesNotExist:
            return Response({"note": ""}, status=200)
    
    if request.method == 'POST':
        note_text = request.data.get('note_text', '').strip()
        if not note_text:
            UserQuestionNote.objects.filter(user=request.user, question_id=question_id).delete()
            return Response({"message": "Note deleted"}, status=200)
        
        UserQuestionNote.objects.update_or_create(
            user=request.user, question_id=question_id, defaults={'note_text': note_text}
        )
        return Response({"message": "Note saved"}, status=201)





# --- 6. DASHBOARD API (FIXED MODEL IMPORT) ---


from django.db.models import Avg, Sum, Count
from .models import UserAnswerLog

# quiz/views.py

# quiz/views.py

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_dashboard_api(request):
    user = request.user
    # 1. FETCH LOGS (Optimized with select_related for performance)
    queryset = UserAnswerLog.objects.filter(user=user).order_by('-attempted_at')
    
    # We use a slice for "Recent Behavior" analysis (Coach Logic needs recent trends)
    recent_logs = queryset[:100] 
    
    # Handle New User Case
    if not recent_logs:
         return Response({
            'username': user.username,
            'stats': {
                'accuracy': 0.0, 'streak': 0, 'weak_subject': "None",
                'coach_card': {'title': "Welcome 👋", 'message': "Start solving to unlock insights."},
                'radar_data': {'logic': 0, 'precision': 0, 'reasoning': 0, 'recall': 0},
                'deep_metrics': {'era_gap': '-', 'sniper_efficiency': 0, 'rush_accuracy': 0},
                # Legacy placeholders to prevent frontend errors
                'wasted_time_mins': 0, 'guess_accuracy': 0, 'dangerous_errors': 0, 'unnecessary_doubts': 0
            }
        })

    # --- 1. BASIC STATS (PRESERVED) ---
    accuracy_data = queryset.aggregate(
        avg_score=Avg(
            Case(
                When(is_correct=True, then=1.0),
                default=0.0,
                output_field=FloatField()
            )
        )
    )
    accuracy = (accuracy_data['avg_score'] or 0.0) * 100
    streak_count = queryset.dates('attempted_at', 'day').count()
    accuracy = (accuracy_data['avg_score'] or 0.0) * 100
    streak_count = queryset.dates('attempted_at', 'day').count()

    # --- 2. ADVANCED INSIGHTS (PRESERVED) ---
    # Insight A: "Time Wasted on Skips"
    skipped_logs = queryset.filter(is_skipped=True)
    wasted_time_seconds = skipped_logs.aggregate(total_time=Sum('time_taken_seconds'))['total_time'] or 0
    wasted_time_mins = round(wasted_time_seconds / 60, 1)

    # Insight B: "Guess Accuracy" (Luck vs Skill)
    low_confidence_logs = queryset.filter(confidence_score__lt=50, is_skipped=False)
    total_guesses = low_confidence_logs.count()
    correct_guesses = low_confidence_logs.filter(is_correct=True).count()
    guess_accuracy = round((correct_guesses / total_guesses) * 100, 1) if total_guesses > 0 else 0

    # Insight C: "Imposter Syndrome" (High Confidence Errors) - TOTAL COUNT
    dangerous_errors_total = queryset.filter(confidence_score__gt=70, is_correct=False).count()

    # Insight D: "Second Guessing" (Gut Check)
    unnecessary_doubts = queryset.filter(is_bookmarked=True, is_correct=True).count()


    # --- 3. WEAKEST SUBJECT (OPTIMIZED) ---
    weak_subject = "None"
    lowest_acc = 100.0
    
    # We ask the DB to group by subject and count totals in ONE step
    subject_stats = queryset.values('question__subject').annotate(
        total=Count('id'),
        correct=Count('id', filter=Q(is_correct=True))
    )
    
    for stat in subject_stats:
        subj = stat['question__subject']
        if not subj: continue
        
        total = stat['total']
        if total > 0:
            acc = (stat['correct'] / total) * 100
            if acc < lowest_acc:
                lowest_acc = acc
                weak_subject = subj

    # --- 4. STRATEGY RADAR (EXISTING + REFINED) ---
    # We use the full queryset for the Radar to show "All Time" strengths
    def get_acc(pattern_list):
        logs = queryset.filter(question__pattern__in=pattern_list)
        if not logs.exists(): return 0.0
        return (logs.filter(is_correct=True).count() / logs.count()) * 100

    score_logic = get_acc(['elim_classical', 'elim_haphazard'])    # Logic
    score_precision = get_acc(['zero_g_statement', 'zero_g_column_2', 'zero_g_column_3']) # Precision
    score_reasoning = get_acc(['assertion_2', 'assertion_3'])      # Reasoning
    score_recall = get_acc(['one_liner', 'fifty_fifty'])           # Recall

    # --- 5. DEEP METRICS (New) ---
    # A. Era Gap
    era_gap_msg = "Balanced"
    if score_logic > 0:
        gap_ratio = score_precision / score_logic
        if gap_ratio < 0.5: era_gap_msg = "Dinosaur 🦕"
        elif gap_ratio > 1.2: era_gap_msg = "Modern 🚀"

    # B. Sniper Efficiency (Using recent logs for current form)
    recent_sniper_logs = [log for log in recent_logs if log.eliminated_options and len(log.eliminated_options) > 0]
    sniper_total = len(recent_sniper_logs)
    sniper_correct = len([log for log in recent_sniper_logs if log.is_correct])
    sniper_efficiency = (sniper_correct / sniper_total * 100) if sniper_total > 0 else 0

    # C. Rush Accuracy
    recent_rushed = [log for log in recent_logs if log.time_taken_seconds < 15 and not log.is_skipped]
    rushed_count = len(recent_rushed)
    rushed_correct = len([log for log in recent_rushed if log.is_correct])
    rush_accuracy = (rushed_correct / rushed_count * 100) if rushed_count > 0 else 100.0


    # --- 6. THE AI COACH LOGIC (FULL MATRIX VERSION) 🤖 ---
    # This logic uses 'recent_logs' to diagnose current behavior.
    
    coach_title = "On Track 🎯"
    coach_message = "Your performance is balanced. Keep practicing consistently."
    
    # -- Data Prep for Matrix --
    total_recent = len(recent_logs)
    skip_count = len([log for log in recent_logs if log.is_skipped])
    skip_rate = (skip_count / total_recent) * 100 if total_recent > 0 else 0
    
    # Recent high confidence errors (Dunning-Kruger check)
    recent_high_conf_errors = len([log for log in recent_logs if log.confidence_score > 80 and not log.is_correct])
    # Recent low confidence correct (Imposter check)
    recent_low_conf_correct = len([log for log in recent_logs if log.confidence_score < 40 and log.is_correct])
    
    # Avg Time on WRONG answers (Overthinker check)
    wrong_logs = [log for log in recent_logs if not log.is_correct and not log.is_skipped]
    avg_time_wrong = sum([log.time_taken_seconds for log in wrong_logs]) / len(wrong_logs) if wrong_logs else 0

    # --- WATERFALL LOGIC ---

    # DIMENSION 1: MINDSET CHECK
    if recent_high_conf_errors > 4:
        coach_title = "Reality Check 🛑" 
        coach_message = "You are marking answers as 'Sure' but getting them wrong. You have dangerous misconceptions. Stop guessing."
    
    elif recent_low_conf_correct > 5:
        coach_title = "The Imposter 🎭"
        coach_message = "Trust your gut! You marked 'Low Confidence' on many questions you actually got right."

    elif skip_rate > 35:
        coach_title = "Risk Averse 🛡️"
        coach_message = "You are skipping too much (>35%). In UPSC, you need calculated risks. Attempt 5 '50-50' questions today."

    # DIMENSION 2: STRATEGY CHECK
    elif score_logic > 80 and score_precision < 40:
        coach_title = "The Gamer 🎮"
        coach_message = "Tactical genius, but factually weak. You fail when Elimination tricks don't work (Zero-G). Read textbooks."

    elif score_precision > 70 and score_reasoning < 40:
        coach_title = "Superficial Reader 📖"
        coach_message = "You know facts but fail 'Assertion-Reasoning'. Ask 'Why?' not just 'What?' when reading."

    # DIMENSION 3: TIME CHECK
    elif rushed_count > 5 and rush_accuracy < 50:
        coach_title = "The Speedster ⚡"
        coach_message = f"Slow Down! You have {int(rush_accuracy)}% accuracy when answering under 15s. You are losing easy marks."

    elif avg_time_wrong > 120:
        coach_title = "The Overthinker ⏳"
        coach_message = "Time Trap! You spend over 2 mins on wrong answers. If you don't know it in 60s, move on."

    # DIMENSION 4: PROCESS CHECK
    elif sniper_total > 5 and sniper_efficiency < 40:
        coach_title = "The 50-50 Loser 📉"
        coach_message = "The 'Final Mile' Problem: You successfully eliminate trash options, but choke on the final choice."

    # --- 7. RETURN MERGED JSON ---
    return Response({
        'username': user.username,
        'stats': {
            # --- Legacy Keys (Preserved) ---
            'accuracy': round(accuracy, 1),
            'streak': streak_count,
            'weak_subject': weak_subject,
            'wasted_time_mins': wasted_time_mins,
            'guess_accuracy': guess_accuracy,
            'dangerous_errors': dangerous_errors_total, # Uses the All-Time count for the Insight Row
            'unnecessary_doubts': unnecessary_doubts,

            # --- New Keys (The Brain) ---
            'coach_card': {
                'title': coach_title,
                'message': coach_message,
            },
            'radar_data': {
                'logic': round(score_logic, 1),
                'precision': round(score_precision, 1),
                'reasoning': round(score_reasoning, 1),
                'recall': round(score_recall, 1),
            },
            'deep_metrics': {
                'era_gap': era_gap_msg,
                'sniper_efficiency': round(sniper_efficiency, 1),
                'rush_accuracy': round(rush_accuracy, 1),
            }
        }
    })
#---USER library API----

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_library_api(request):
    user = request.user
    
    # NEW: Filters
    subject_filter = request.query_params.get('subject')
    has_note_filter = request.query_params.get('has_note')  # 'true' or None
    
    latest_logs = UserAnswerLog.objects.filter(
        user=user, is_bookmarked=True, is_cleared_from_library=False
    )
    
    if subject_filter:
        latest_logs = latest_logs.filter(question__subject=subject_filter)
    
    latest_logs = latest_logs.values('question_id').annotate(latest_id=Max('id'))
    target_ids = [item['latest_id'] for item in latest_logs]
    
    library_items = UserAnswerLog.objects.filter(id__in=target_ids)\
        .select_related('question')\
        .prefetch_related('question__options')\
        .order_by('-attempted_at')
    
    # NEW: Has Note Filter (after fetching, since it's derived)
    if has_note_filter == 'true':
        library_items = [item for item in library_items if user.notes.filter(question=item.question).exists()]
    elif has_note_filter == 'false':
        library_items = [item for item in library_items if not user.notes.filter(question=item.question).exists()]
    
    data = []
    for log in library_items:
        has_note = user.notes.filter(question=log.question).exists()
        options_data = [{'id': opt.id, 'text_content': opt.text_content, 'option_label': opt.option_label,
                         'is_correct': opt.is_correct, 'explanation_text': opt.explanation_text,
                         'image_url': opt.image_url, 'mnemonic_text': opt.mnemonic_text} for opt in log.question.options.all()]
        
        data.append({
            'log_id': log.id, 'question_id': log.question.id, 'text': log.question.text, 'question_image_url': log.question.question_image_url,
            'subject': log.question.subject, 'tags': log.question.tags, 'source_mode': log.source_mode,
            'has_note': has_note, 'note_text': user.notes.filter(question=log.question).first().note_text if has_note else '',  # NEW: Include full text
            'options': options_data
        })
    
    return Response(data)

# --- NEW: SAFE DELETE API ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def remove_bookmark_api(request):
    question_id = request.data.get('question_id')
    if not question_id:
        return Response({"error": "Missing ID"}, status=400)
        
    # LOGIC: "Safe Delete"
    # We find ALL logs for this question and mark them as cleared from library.
    # This keeps 'is_bookmarked=True' for history reports, but hides them from the active list.
    # 1. Hide from Library (Keep Exam History)
    UserAnswerLog.objects.filter(
        user=request.user, 
        question_id=question_id
    ).update(is_cleared_from_library=True)
    # 2. DELETE THE NOTE
    UserQuestionNote.objects.filter(user=request.user, question_id=question_id).delete()
    
    return Response({"message": "Bookmark and note removed"}, status=200)
    # --- 8. THE TIME MACHINE (History Graph API) ---
# quiz/views.py

class UserHistoryAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        # Fetch last 30 days of logs
        logs = UserAnswerLog.objects.filter(user=user).order_by('attempted_at')
        
        if not logs.exists():
            return Response({"dates": [], "logic": [], "precision": []})

        from collections import defaultdict
        
        # 1. Use a dictionary that tracks the REAL date object for sorting later
        # Format: { "12-Oct": { 'stats': {...}, 'real_date': datetime_obj } }
        history_map = defaultdict(lambda: {
            'logic_correct': 0, 'logic_total': 0, 
            'prec_correct': 0, 'prec_total': 0,
            'real_date': None 
        })

        for log in logs:
            # Convert UTC to Local Time (Important so late night exams appear on correct day)
            local_dt = timezone.localtime(log.attempted_at)
            date_str = local_dt.strftime("%d-%b") # e.g., "12-Oct"
            
            # Init the real_date if not set
            if history_map[date_str]['real_date'] is None:
                history_map[date_str]['real_date'] = local_dt

            # Check Pattern Type
            pat = log.question.pattern
            is_logic = pat in ['elim_classical', 'elim_haphazard']
            is_precision = pat.startswith('zero_g')
            
            if is_logic:
                history_map[date_str]['logic_total'] += 1
                if log.is_correct: history_map[date_str]['logic_correct'] += 1
            elif is_precision:
                history_map[date_str]['prec_total'] += 1
                if log.is_correct: history_map[date_str]['prec_correct'] += 1

        # 2. SORTING FIX: Sort by 'real_date', not 'date_str'
        # This ensures Feb 28 comes before Mar 1
        sorted_items = sorted(history_map.items(), key=lambda x: x[1]['real_date'])
        
        # Take the last 7 days AFTER sorting correctly
        final_items = sorted_items[-7:]

        # Format for Frontend
        dates = []
        logic_scores = []
        precision_scores = []

        for d_str, stats in final_items:
            # Calculate Logic Score %
            l_score = 0
            if stats['logic_total'] > 0:
                l_score = (stats['logic_correct'] / stats['logic_total']) * 100
            
            # Calculate Precision Score %
            p_score = 0
            if stats['prec_total'] > 0:
                p_score = (stats['prec_correct'] / stats['prec_total']) * 100
            
            dates.append(d_str)
            logic_scores.append(round(l_score, 1))
            precision_scores.append(round(p_score, 1))

        return Response({
            "dates": dates,
            "logic": logic_scores,
            "precision": precision_scores
        })

# --- 9. MOCK EXAM SIMULATOR (The Final Boss) ---
class MockExamGeneratorAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # 1. Define the "Hostile Mix" (20 Questions Total)
        # We force the user to face their fears (Zero-G).
        
        # A. 6 Zero-G Questions (30%) - The Killer
        zero_g_qs = list(Question.objects.filter(pattern__startswith='zero_g').order_by('?')[:6])
        
        # B. 6 Elimination Questions (30%) - The Comfort Zone
        elim_qs = list(Question.objects.filter(pattern__startswith='elim').order_by('?')[:6])
        
        # C. 4 Reasoning Questions (20%) - The Link
        reason_qs = list(Question.objects.filter(pattern__startswith='assertion').order_by('?')[:4])
        
        # D. 4 One-Liners (20%) - The Speed Check
        speed_qs = list(Question.objects.filter(pattern='one_liner').order_by('?')[:4])
        
        # Combine & Shuffle
        final_pool = zero_g_qs + elim_qs + reason_qs + speed_qs
        import random
        random.shuffle(final_pool)
        
        # Serialize
        serializer = QuestionSerializer(final_pool, many=True)
        return Response(serializer.data)
# quiz/views.py (Add to bottom)

class ExamAnalysisAPI(APIView):
    permission_classes = [IsAuthenticated]

    def _calculate_session_stats(self, logs):
        # ... (Same Aggregation Logic as before) ...
        unique_qs = {} 
        for log in logs:
            qid = log.question.id
            if qid not in unique_qs:
                unique_qs[qid] = { 'total_time': 0, 'latest_log': log, 'timestamp': log.attempted_at }
            unique_qs[qid]['total_time'] += log.time_taken_seconds
            if log.attempted_at >= unique_qs[qid]['timestamp']:
                unique_qs[qid]['latest_log'] = log
                unique_qs[qid]['timestamp'] = log.attempted_at
        # Buckets: 0, 25, 50, 75, 100
        conf_matrix = {
            0:   {'correct': 0, 'wrong': 0},
            25:  {'correct': 0, 'wrong': 0},
            50:  {'correct': 0, 'wrong': 0},
            75:  {'correct': 0, 'wrong': 0},
            100: {'correct': 0, 'wrong': 0}
        }

        # Metrics
        correct = 0; wrong = 0; skipped = 0; silly_mistakes = 0
        quadrants = {"q1_sniper": [], "q2_optimal": [], "q3_rush": [], "q4_trap": []}
        full_logs_out = []; heatmap_stats = {}

        for qid, data in unique_qs.items():
            log = data['latest_log']
            t_time = data['total_time']
            
            if log.is_correct: correct += 1
            elif log.is_skipped: skipped += 1
            else: wrong += 1
            
            if not log.is_correct and not log.is_skipped:
                if t_time < 15 or log.confidence_score > 80: silly_mistakes += 1
            
            # Quadrants
            q_info = {"id": log.question.id, "text": log.question.text, "time": t_time, "is_correct": log.is_correct}
            if log.is_correct:
                if t_time < 40: quadrants['q1_sniper'].append(q_info)
                else: quadrants['q2_optimal'].append(q_info)
            elif not log.is_skipped:
                if t_time < 20: quadrants['q3_rush'].append(q_info)
                elif t_time > 60: quadrants['q4_trap'].append(q_info)
                
            # Heatmap
            subj = log.question.subject
            
            if subj not in heatmap_stats: 
                heatmap_stats[subj] = {
                    'attempted': 0, 'correct': 0, 'wrong': 0, 'skipped': 0,
                    'total_time': 0, 'silly_mistakes': 0
                }
            
            # Count Skips separately
            if log.is_skipped:
                heatmap_stats[subj]['skipped'] += 1
            else:
                heatmap_stats[subj]['attempted'] += 1
                heatmap_stats[subj]['total_time'] += log.time_taken_seconds
                
                if log.is_correct:
                    heatmap_stats[subj]['correct'] += 1
                else:
                    heatmap_stats[subj]['wrong'] += 1
                    # Track "Rushed Errors" (<15s) for the footer
                    if log.time_taken_seconds < 15:
                        heatmap_stats[subj]['silly_mistakes'] += 1
            
            # Full Logs
            full_logs_out.append({
                "question_id": log.question.id,
                "time_taken": t_time,
                "is_correct": log.is_correct,
                "is_skipped": log.is_skipped,
                "selected_option_id": log.selected_option_id 
            })
            if not log.is_skipped:
                # Snap confidence to nearest bucket (0, 25, 50, 75, 100)
                score = log.confidence_score
                bucket = 0
                if score >= 88: bucket = 100
                elif score >= 63: bucket = 75
                elif score >= 38: bucket = 50
                elif score >= 13: bucket = 25
                else: bucket = 0
                
                if log.is_correct:
                    conf_matrix[bucket]['correct'] += 1
                else:
                    conf_matrix[bucket]['wrong'] += 1

        actual_score = (correct * 2) - (wrong * 0.66)
        lost_marks = silly_mistakes * 2.66
        potential_score = actual_score + lost_marks
        total_qs = len(unique_qs)
        accuracy = (correct / total_qs * 100) if total_qs > 0 else 0

        heatmap_list = []
        for subj, stats in heatmap_stats.items():
            attempts = stats['attempted']
            correct = stats['correct']
            wrong = stats['wrong']
            skipped = stats['skipped']
            
            # Only show if the user interacted with the subject at all
            if attempts > 0:
                acc = (correct / attempts) * 100 if attempts > 0 else 0.0
                
                # UPSC Marking Scheme (+2, -0.66)
                net_marks = (correct * 2) - (wrong * 0.66)
                subj_lost_marks = wrong * 0.66
                avg_time = stats['total_time'] / attempts if attempts > 0 else 0
                
                heatmap_list.append({
                    'subject': subj, 
                    'accuracy': round(acc, 1),
                    'net_marks': round(net_marks, 2),
                    'lost_marks': round(subj_lost_marks, 2),
                    'avg_time': round(avg_time, 0),
                    'correct': correct,
                    'wrong': wrong,
                    'skipped': skipped,
                    'silly_mistakes': stats['silly_mistakes']
                })
        
        heatmap_list.sort(key=lambda x: x['accuracy'])

        return {
            "score_card": {
                "actual_score": round(actual_score, 2),
                "potential_score": round(potential_score, 2),
                "lost_marks": round(lost_marks, 2),
                "accuracy": round(accuracy, 1)
            },
            "quadrants": quadrants,
            "heatmap": heatmap_list,
            "full_logs": full_logs_out,
            "total_qs": total_qs,
            "confidence_matrix": conf_matrix
            
        }

    def get(self, request, session_id):
        user = request.user
        
        # 1. Fetch Current Session [PRESERVED]
        current_logs = UserAnswerLog.objects.filter(user=user, session_id=session_id).select_related('question')
        if not current_logs.exists():
            return Response({"error": "Session not found"}, status=404)

        current_stats = self._calculate_session_stats(current_logs)
        
        # --- [NEW] FEATURE 1: HISTORY RECONSTRUCTION PACK ---
        # We need this so the App can "Re-Build" the exam screen when clicking history.
        # We use a set to ensure unique questions.
        unique_questions = list({log.question for log in current_logs})
        reconstruction_pack = QuestionSerializer(unique_questions, many=True).data

        # --- 2. INTELLIGENT CONTEXT DETECTION (Overlap Aware) [PRESERVED] ---
        # (I am using your exact variable names here)
        first_q = current_logs.first().question
        context_exam = first_q.exam_name
        
        # --- [NEW] FEATURE 2: CUTOFF AI BRAIN ---
        # We place this here because we just found 'context_exam' and 'first_q.year'
        # --- [NEW] FEATURE 2: CUTOFF AI BRAIN (DATABASE VERSION) ---
        cutoff_analysis = {"status": "N/A", "gap": 0, "message": "No official data."}
        
        # GATEKEEPER: Only show cutoff if this is a "Year-wise" exam
        # We check if the session_id starts with "year_" (which we set in Flutter)
        is_year_exam = str(session_id).startswith("year_")
        
        if is_year_exam:
            context_year = first_q.year
            
            # 1. Query the Database
            cutoff_obj = ExamCutoff.objects.filter(exam_name=context_exam, year=context_year).first()
            
            if cutoff_obj:
                # 2. Calculate Gap (Based on General Category by default)
                official_cutoff = cutoff_obj.general
                user_score = current_stats['score_card']['actual_score']
                gap = user_score - official_cutoff
                
                if gap >= 0:
                    status_label = "CLEARED" 
                    msg = f"Safe Zone! (+{round(gap, 2)})"
                else:
                    status_label = "FAILED"
                    msg = f"Missed by {abs(round(gap, 2))}"

                # 3. Construct the Full Package (General + Categories)
                cutoff_analysis = {
                    "status": status_label,
                    "gap": round(gap, 2),
                    "message": msg,
                    "breakdown": {
                        "General": cutoff_obj.general,
                        "EWS": cutoff_obj.ews,
                        "OBC": cutoff_obj.obc,
                        "SC": cutoff_obj.sc,
                        "ST": cutoff_obj.st,
                    },
                    "is_official": cutoff_obj.is_official
                }

        # --- CONTINUING YOUR PRESERVED LOGIC ---
        
        # A. Detect "Common Denominators" across the session [PRESERVED]
        OFFICIAL_SUBJECTS = [
            "History", "Polity", "Geography", "Economy", "Environment", 
            "Science & Tech", "International Relations", "Current Affairs", "Art & Culture"
        ]
        
        session_questions = [log.question for log in current_logs]
        
        # Find Common Year (if any) [PRESERVED]
        years = set(q.year for q in session_questions)
        is_pure_year = (len(years) == 1)
        target_year = list(years)[0] if is_pure_year else None
        
        # Find Common Subject (Checking Primary Subject AND Tags) [PRESERVED]
        target_subject = None
        for candidate in OFFICIAL_SUBJECTS:
            is_common = True
            for q in session_questions:
                in_primary = (q.subject == candidate)
                in_tags = (candidate in (q.tags or ""))
                if not (in_primary or in_tags):
                    is_common = False
                    break
            if is_common:
                target_subject = candidate
                break

        # --- [NEW] FALLBACK: Query params from Flutter when auto-detection fails ---
        # Prevents global history when subject/year strings don't match OFFICIAL_SUBJECTS
        year_param = request.query_params.get('year')
        subject_param = request.query_params.get('subject')
        if target_year is None and year_param and str(year_param).strip().isdigit():
            target_year = int(year_param)
        if target_subject is None and subject_param and str(subject_param).strip():
            target_subject = str(subject_param).strip()
        
        # 1. Base Query: Get all exams for this user & exam name (e.g., UPSC CSE)
        # --- B. HISTORY FILTERING (STRICT CONTEXT) ---
        history_query = UserAnswerLog.objects.filter(
            user=user, 
            session_id__isnull=False, 
            question__exam_name=context_exam, 
            source_mode='exam'
        ).exclude(session_id=session_id)

        year_param = request.query_params.get('year')
        subject_param = request.query_params.get('subject')
        
        if year_param and str(year_param).strip().isdigit():
            # STRICT: Only show history specifically tagged with this year
            history_query = history_query.filter(session_id__startswith=f"year_{year_param}_")
            
        elif subject_param:
            # STRICT: Only show history specifically tagged with this subject
            clean_subj = "".join([c for c in subject_param if c.isalnum()])
            history_query = history_query.filter(session_id__startswith=f"subj_{clean_subj}_")
        
        # Get Final Session IDs [PRESERVED]
        past_session_ids = history_query.values_list('session_id', flat=True).distinct()
        
        # Order by Date [PRESERVED]
        past_sessions_meta = UserAnswerLog.objects.filter(
            session_id__in=past_session_ids
        ).values('session_id').annotate(
            date=Max('attempted_at')
        ).order_by('-date')[:5]
        
        history_list = []
        for meta in past_sessions_meta:
            sid = meta['session_id']
            
            # FAST AGGREGATION: 
            # Instead of calculating heatmaps (heavy), we just count Correct/Wrong (instant).
            h_agg = UserAnswerLog.objects.filter(session_id=sid).aggregate(
                correct=Count('id', filter=Q(is_correct=True)),
                wrong=Count('id', filter=Q(is_correct=False, is_skipped=False)),
                total=Count('id')
            )
            
            # Safe Logic (Handle None values if DB is empty)
            c = h_agg['correct'] or 0
            w = h_agg['wrong'] or 0
            t = h_agg['total'] or 0
            
            # UPSC Scoring Logic (+2, -0.66)
            score = (c * 2) - (w * 0.66)
            acc = (c / t * 100) if t > 0 else 0
            
            history_list.append({
                "session_id": sid,
                "date": timezone.localtime(meta['date']).strftime("%d %b, %H:%M"), 
                "score": round(score, 2),
                "accuracy": round(acc, 1),
                "total": t
            })

        # --- 3. GROWTH REPORT [PRESERVED] ---
        growth_report = {"has_history": False}
        if len(history_list) > 0:
            last_sid = history_list[0]['session_id']
            last_logs = UserAnswerLog.objects.filter(session_id=last_sid).select_related('question')
            last_stats = self._calculate_session_stats(last_logs)
            
            curr_map = {log['question_id']: log['is_correct'] for log in current_stats['full_logs']}
            prev_map = {log['question_id']: log['is_correct'] for log in last_stats['full_logs']}
            
            retention_fix = 0
            false_positive = 0
            stable_correct = 0
            persistent_error = 0
            
            for qid, curr_correct in curr_map.items():
                if qid in prev_map:
                    prev_correct = prev_map[qid]
                    if not prev_correct and curr_correct: retention_fix += 1
                    elif prev_correct and not curr_correct: false_positive += 1
                    elif prev_correct and curr_correct: stable_correct += 1
                    elif not prev_correct and not curr_correct: persistent_error += 1
            
            growth_report = {
                "has_history": True,
                "retention_fix": retention_fix,
                "false_positive": false_positive,
                "stable_correct": stable_correct,
                "persistent_error": persistent_error
            }

        return Response({
            "score_card": current_stats['score_card'],
            # --- [NEW] ADDED KEYS ---
            "cutoff_analysis": cutoff_analysis,
            "reconstruction_pack": reconstruction_pack,
            # ------------------------
            "quadrants": current_stats['quadrants'],
            "heatmap": current_stats['heatmap'],
            "full_logs": current_stats['full_logs'],
            "history": history_list,
            "growth_report": growth_report,
            "confidence_matrix": current_stats['confidence_matrix']
        })
    
# --- 10. PAYMENT VERIFICATION API (The Missing Part) ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_payment_api(request):
    """
    Called by Flutter after Razorpay success.
    Updates the user's status to Premium.
    """
    # In a real production app, verify the 'razorpay_signature' here.
    # For now, we update the status based on the success signal.
    
    user = request.user
    user.is_premium = True
    user.save()
    
    return Response({
        "message": "Premium Unlocked!",
        "is_premium": True
    }, status=status.HTTP_200_OK)    