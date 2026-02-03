from django.core.management.base import BaseCommand
from quiz.models import Question, KeywordAnalysis
import re

class Command(BaseCommand):
    help = 'Scans all questions to analyze extreme words (All, None, Only, etc.)'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting Keyword Analysis...")

        # 1. Clear old data so we don't get duplicates
        deleted_count, _ = KeywordAnalysis.objects.all().delete()
        self.stdout.write(f"Cleared {deleted_count} old analysis records.")

        # 2. Define the Tricky Words & Phrases
        keywords = [
            'All', 'None', 'Only', 'Drastically', 'Generally', 
            'Some', 'Can be', 'Always', 'Never',
            'Drastically increase', 'Exponentially', 'Steadily'
        ]
        
        # Prefetch 'options' to optimize database performance
        questions = Question.objects.prefetch_related('options').all()
        count = 0

        # 3. Analyze Loop
        # We loop through Keywords FIRST, then Questions. 
        # This ensures we handle each word specifically.
        for word in keywords:
            pattern = r'\b' + re.escape(word) + r'\b'
            
            for q in questions:
                found_in_question = False
                is_true_usage = False # Default to False (Trap)
                
                # Scan all options for this specific word
                for option in q.options.all():
                    if re.search(pattern, option.text_content, re.IGNORECASE):
                        found_in_question = True
                        
                        # If the word is in the CORRECT option, it's a "True Usage" (Safe)
                        if option.is_correct:
                            is_true_usage = True

                # Only save if we actually found the word in this question
                if found_in_question:
                    KeywordAnalysis.objects.create(
                        question=q,
                        keyword=word,
                        is_true_usage=is_true_usage, # True if in correct answer, False if in wrong answer
                        year=q.year,
                        exam_name=q.exam_name
                    )
                    count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully analyzed {count} keyword occurrences!"))