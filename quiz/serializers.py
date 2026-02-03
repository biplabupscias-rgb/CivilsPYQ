from rest_framework import serializers

from .models import Question, Option, KnowledgeConcept, KeywordAnalysis
import re

# 1. Serializer for the Wiki Concepts
class KnowledgeConceptSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeConcept
        fields = '__all__'

# 2. Serializer for Options (With Cleaning)
class OptionSerializer(serializers.ModelSerializer):
    text_content = serializers.SerializerMethodField()

    class Meta:
        model = Option
        fields = ['id', 'option_label', 'text_content', 'is_correct', 
                  'explanation_text', 'image_url', 'video_url', 'mnemonic_text']

    def get_text_content(self, obj):
        # Remove {{T:Word}} and {{F:Word}} patterns, keeping just "Word"
        # Example: "{{F:All}} types" becomes "All types"
        clean = re.sub(r'\{\{[TF]:(.*?)\}\}', r'\1', obj.text_content)
        return clean

# 3. Serializer for Questions (With Cleaning)
class QuestionSerializer(serializers.ModelSerializer):
    text = serializers.CharField(source='clean_text', read_only=True)
    options = OptionSerializer(many=True, read_only=True)
   

    class Meta:
        model = Question
        fields = ['id', 'exam_name', 'year', 'subject', 'pattern', 'text', 'tags', 'question_image_url', 'options']

    
# 4. Serializer for Graph Data
class KeywordAnalysisSerializer(serializers.ModelSerializer):
    class Meta:
        model = KeywordAnalysis
        fields = '__all__'
# --- 5. AUTH SERIALIZERS ---
from django.contrib.auth import authenticate

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()

    def validate(self, data):
        user = authenticate(**data)
        if user and user.is_active:
            return {
                'token': user.auth_token.key,
                'username': user.username,
                'is_premium': getattr(user, 'is_premium', False), # Safe check
            }
        raise serializers.ValidationError("Incorrect Credentials")
