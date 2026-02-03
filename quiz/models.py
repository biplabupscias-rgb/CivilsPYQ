from django.db import models
from django.conf import settings 
from django.apps import apps
from django.contrib.auth.models import AbstractUser
import re 
import uuid
# --- HELPER: CONVERT DRIVE LINKS ---
def clean_drive_url(url):
    """
    Detects if a URL is a Google Drive 'View' link and converts it 
    to a 'Direct Download' link that Flutter can render.
    """
    if not url: 
        return url
    
    # Check if it is a Google Drive Link
    if "drive.google.com" in url and "/d/" in url:
        # Regex to extract the FILE ID (the part between /d/ and /view)
        match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
        if match:
            file_id = match.group(1)
            # Return the Direct Link format
            return f"https://drive.google.com/uc?export=view&id={file_id}"
            
    return url # Return original if it's already a direct link

# --- 0. CUSTOM USER MODEL ---
class CustomUser(AbstractUser):
    is_premium = models.BooleanField(default=False) 
    phone_number = models.CharField(max_length=15, blank=True, null=True)

    groups = models.ManyToManyField(
        'auth.Group', related_name="customuser_groups", blank=True,
        help_text="The groups this user belongs to.", verbose_name="groups",
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission', related_name="customuser_permissions", blank=True,
        help_text="Specific permissions for this user.", verbose_name="user permissions",
    )

# --- HELPER FUNCTION FOR TAGGING ---
def process_manual_tags(instance, text_field_value, exam_name, year):
    true_matches = re.findall(r'\{\{T:(.*?)\}\}', text_field_value)
    false_matches = re.findall(r'\{\{F:(.*?)\}\}', text_field_value)
    KeywordAnalysis = apps.get_model('quiz', 'KeywordAnalysis')

    for word in true_matches:
        KeywordAnalysis.objects.create(
            question=instance if isinstance(instance, Question) else instance.question,
            keyword=word, is_true_usage=True, year=year, exam_name=exam_name
        )
    for word in false_matches:
        KeywordAnalysis.objects.create(
            question=instance if isinstance(instance, Question) else instance.question,
            keyword=word, is_true_usage=False, year=year, exam_name=exam_name
        )
    return text_field_value

# --- 1. CORE TABLES (Concept, Question, Option, KeywordAnalysis) ---
class KnowledgeConcept(models.Model):
    term = models.CharField(max_length=200, unique=True)
    definition = models.TextField()
    detailed_explanation = models.TextField(blank=True)
    image_url = models.URLField(blank=True, null=True)
    video_url = models.URLField(blank=True, null=True)
    def save(self, *args, **kwargs):
        self.image_url = clean_drive_url(self.image_url)
        super().save(*args, **kwargs)
    def __str__(self): return self.term

class Question(models.Model):
    SUBJECT_CHOICES = [
        ('History', 'History'), ('Polity', 'Polity'), ('Geography', 'Geography'),
        ('Economy', 'Economy'), ('Science & Tech', 'Science & Tech'), ('International Relations', 'International Relations'), 
        ('Environment', 'Environment'),
        ('Current Affairs', 'Current Affairs'), ('Art & Culture', 'Art & Culture'),
    ]
    PATTERN_CHOICES = [
        # Category 1: Elimination (Logic Zone)
        ('elim_classical', 'Classical Elimination (Symmetric)'),
        ('elim_haphazard', 'Haphazard Elimination 🧩'), 
        
        # Category 2: Non-Elimination (Zero-G Zone)
        ('zero_g_statement', 'Zero-G Statement (Only 1/2) 🚀'),
        ('zero_g_column_2', 'Zero-G Column (2-Col Match)'),
        ('zero_g_column_3', 'Zero-G Column (3-Col Match) 💀'),
        ('fifty_fifty', '50-50 Dilemma'),

        # Category 3: Assertion (Because Zone)
        ('assertion_2', 'Assertion (2-Statement)'),
        ('assertion_3', 'Assertion (3-Statement Mutant) 🧬'),

        # Category 4: Speed Zone
        ('one_liner', 'One Liner (Direct MCQ)'),
    ]
    exam_name = models.CharField(max_length=50, default="UPSC CSE")
    year = models.IntegerField(default=2025)
    subject = models.CharField(max_length=50, choices=SUBJECT_CHOICES)
    text = models.TextField()
    question_image_url = models.URLField(blank=True, null=True, help_text="Link to diagram or table image")
    tags = models.CharField(max_length=255, blank=True, null=True)
    pattern = models.CharField(
        max_length=50, 
        choices=PATTERN_CHOICES, 
        default='one_liner',
        help_text="The structural pattern of the question."
    )
    @property
    def clean_text(self):
        """Returns text without [IMAGE] tags for the App"""
        if self.text:
            
            clean = re.sub(r'\{\{[TF]:(.*?)\}\}', r'\1', self.text)
            return clean.strip()
        return ""

    def save(self, *args, **kwargs):
        self.question_image_url = clean_drive_url(self.question_image_url)
        super().save(*args, **kwargs)
        KeywordAnalysis = apps.get_model('quiz', 'KeywordAnalysis')
        KeywordAnalysis.objects.filter(question=self).delete()
        process_manual_tags(self, self.text, self.exam_name, self.year)
        for opt in self.options.all():
            process_manual_tags(opt, opt.text_content, self.exam_name, self.year)

    def __str__(self): return f"{self.exam_name} ({self.year}) - {self.text[:50]}..."

class Option(models.Model):
    question = models.ForeignKey(Question, related_name="options", on_delete=models.CASCADE)
    option_label = models.CharField(max_length=1) 
    text_content = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)
    explanation_text = models.TextField(blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    video_url = models.URLField(blank=True, null=True)
    mnemonic_text = models.TextField(blank=True, null=True)
    mnemonic_color = models.CharField(max_length=7, default="#FFF9C4")

    def save(self, *args, **kwargs):
        self.image_url = clean_drive_url(self.image_url)
        super().save(*args, **kwargs)
        self.question.save()
    def __str__(self): return f"({self.option_label}) {self.text_content[:30]}"

class KeywordAnalysis(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='keyword_analytics')
    keyword = models.CharField(max_length=100) 
    is_true_usage = models.BooleanField() 
    year = models.IntegerField()
    exam_name = models.CharField(max_length=100)
    def __str__(self): return f"{self.keyword} ({'Safe' if self.is_true_usage else 'Trap'})"

class TopicMedia(models.Model):
    tag = models.CharField(max_length=100, unique=True)
    video_url = models.URLField()
    def __str__(self): return f"Video for #{self.tag}"

# --- 2. USER ANSWER LOG (THE BIG UPDATE) ---
# In quiz/models.py

class UserAnswerLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='answer_logs')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    selected_option = models.ForeignKey(Option, on_delete=models.SET_NULL, null=True, blank=True)
    
    # --- Performance Fields ---
    is_correct = models.BooleanField(default=False)
    is_skipped = models.BooleanField(default=False)
    time_taken_seconds = models.PositiveIntegerField(default=0)
    
    # --- Behavioral Fields (NEW) ---
    confidence_score = models.IntegerField(default=100) # 0 to 100
    is_bookmarked = models.BooleanField(default=False)
    is_cleared_from_library = models.BooleanField(default=False)
    eliminated_options = models.JSONField(default=list, blank=True)

    # --- NEW FIELD: SOURCE TAGGING ---
    # This tracks if this log happened during an 'exam' or 'practice'
    source_mode = models.CharField(
        max_length=20, 
        choices=[('exam', 'Exam'), ('practice', 'Practice')], 
        default='practice'
    )

    attempted_at = models.DateTimeField(auto_now_add=True)
    session_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)

    class Meta:
        ordering = ['-attempted_at']
        indexes = [
            models.Index(fields=['user', 'session_id']), # Optimization for analysis lookups
        ]

    def __str__(self):
        status = "Skipped" if self.is_skipped else ("Correct" if self.is_correct else "Wrong")
        return f"{self.user.username} - Q{self.question.id} - {status}"

# --- 3. USER NOTES (The Digital Notebook) ---

class UserQuestionNote(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notes')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    note_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
           # Ensures one note per question per user (no duplicates)
        unique_together = ('user', 'question') # One note per question per user

    def __str__(self):
        return f"Note: {self.user.username} - Q{self.question.id}"
    

