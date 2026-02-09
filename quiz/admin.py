import os
from django.contrib import admin
from django import forms 
from django.forms.models import BaseInlineFormSet
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin
from dotenv import load_dotenv
import google.generativeai as genai
from groq import Groq
from import_export.admin import ImportExportModelAdmin
from .admin_resource import QuestionResource

# Import models
from .models import (
    Question, Option, KnowledgeConcept, KeywordAnalysis, 
    TopicMedia, CustomUser, UserAnswerLog, ExamCutoff
)

# --- CONFIG ---
load_dotenv()
api_key = os.getenv('GROQ_API_KEY')  # Changed from GOOGLE_API_KEY
if api_key:
    client = Groq(api_key=api_key)  # This is the new Groq client

# --- ACTIONS ---
@admin.action(description='✨ Auto-Generate Tags')
def generate_tags(modeladmin, request, queryset):
    if not api_key:
        messages.error(request, "API Key missing.")
        return
    count = 0
    for question in queryset:
        try:
            prompt = f"Read the UPSC-style question: '{question.text}'. Generate 5 relevant comma-separated tags, inferring context like historical dynasties, periods, or topics (e.g., for a temple question, include 'Chola Dynasty' if relevant). Output ONLY the tags, no explanations."
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50
            )
            if response.choices[0].message.content:
                question.tags = response.choices[0].message.content.strip()
                question.save()
                count += 1
        except Exception as e:
            messages.error(request, f"Error QID {question.id}: {e}")
    messages.success(request, f"Tagged {count} questions!")

# --- SMART OPTION DEFAULTS (A, B, C, D) ---
class OptionFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only pre-fill if we are creating a NEW question (not editing old one)
        if not self.instance.pk:
            defaults = ['A', 'B', 'C', 'D']
            for index, form in enumerate(self.forms):
                if index < len(defaults):
                    form.initial['option_label'] = defaults[index]

class OptionInline(admin.TabularInline):
    model = Option
    formset = OptionFormSet # <--- Connects the Smart Logic
    extra = 4
    

# --- ADMINS ---
@admin.register(Question)
class QuestionAdmin(ImportExportModelAdmin):
    resource_class = QuestionResource
    inlines = [OptionInline]
    
    # 1. CLEANER LIST (Removed list_editable)
    list_display = ('text_preview', 'subject', 'exam_name', 'year', 'pattern', 'tags', 'image_status')
    
    # Removed list_editable as requested
    
    list_filter = ('exam_name', 'year', 'subject', 'pattern')
    search_fields = ('text', 'tags')
    actions = [generate_tags]
    
    save_on_top = True

    fieldsets = (
        ('Question & Media', {
            'fields': ('text', 'question_image_url')
        }),
        ('Categorization', {
            'fields': (('subject', 'year', 'exam_name'), ('pattern', 'tags')),
            'classes': ('collapse',), 
        }),
    )

    def text_preview(self, obj):
        return obj.text[:60] + "..." if len(obj.text) > 60 else obj.text
    text_preview.short_description = "Question Text"

    def image_status(self, obj):
        return "📷 Yes" if obj.question_image_url else "-"
    image_status.short_description = "Image"

@admin.register(KnowledgeConcept)
class KnowledgeConceptAdmin(admin.ModelAdmin):
    list_display = ('term', 'definition')
    search_fields = ('term',)

@admin.register(KeywordAnalysis)
class KeywordAnalysisAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'year', 'is_true_usage')
    list_filter = ('keyword', 'is_true_usage', 'year')

@admin.register(UserAnswerLog)
class UserAnswerLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'question', 'is_correct', 'attempted_at')
    list_filter = ('is_correct', 'attempted_at')

@admin.register(TopicMedia)
class TopicMediaAdmin(admin.ModelAdmin):
    list_display = ('tag', 'video_url')

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'email', 'is_premium', 'is_staff']
    list_editable = ['is_premium'] 
    
    fieldsets = UserAdmin.fieldsets + (
        ('Subscription Status', {'fields': ('is_premium',)}),
    )
@admin.register(ExamCutoff)
class ExamCutoffAdmin(admin.ModelAdmin):
    list_display = ('exam_name', 'year', 'general', 'obc', 'sc', 'st', 'is_official')
    list_filter = ('exam_name', 'is_official')
    ordering = ('-year',)
    list_editable = ('general', 'is_official') # Allows quick editing in the list view
