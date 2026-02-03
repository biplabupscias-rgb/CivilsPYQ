from django.contrib import admin
from django.urls import path
from quiz import views
from quiz.views import (
    QuestionList, ConceptDetailView, KeywordAnalysisAPI, KeywordTrendAPI, GameModeView, signup_api, login_api, save_user_answer, user_note_api, user_dashboard_api, user_library_api,remove_bookmark_api  # ← added here
)

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # --- AUTH URLS ---
    path('api/auth/signup/', signup_api),
    path('api/auth/login/', login_api),

    # URL for fetching Questions
    path('api/questions/', QuestionList.as_view()),
    
    # URL for fetching Wiki Concepts
    path('api/concept/<str:term>/', ConceptDetailView.as_view()), 
    
    # URL for the Keywords
    path('api/analysis/keywords/', KeywordAnalysisAPI.as_view()),

    # URL for the Deep Dive Graph
    path('api/analysis/trend/', KeywordTrendAPI.as_view()),

    # URL for Game Mode
    path('api/game/start/', GameModeView.as_view()),
    path('api/user/answer-log/', save_user_answer),
 
    # --- NEW NOTE API ---
    path('api/user/note/', user_note_api, name='user_note'),
    #----API for the Dashboard----
    path('api/user/dashboard/', user_dashboard_api),

    path('api/user/library/', user_library_api),
    path('api/user/library/remove/', remove_bookmark_api),
    
    path('api/user/history/', views.UserHistoryAPI.as_view(), name='user-history'),
    path('api/exam/mock/', views.MockExamGeneratorAPI.as_view(), name='mock-exam'),
    path('api/exam/analysis/<str:session_id>/', views.ExamAnalysisAPI.as_view(), name='exam-analysis'),
    path('api/payment/success/', views.verify_payment_api, name='payment_success'),
]
