from django.urls import path
from . import views
from . import conversations, system_views
from .login import LimitedLoginView

urlpatterns = [
    path('system/', system_views.system_view, name='system'),
    path('system/chats/<uuid:chat_id>/', system_views.chat_inspect, name='chat-inspect'),
    path('trash/', system_views.trash_page, name='trash'),
    path('api/conversations/', conversations.list_view),
    path('api/conversations/<uuid:chat_id>/', conversations.detail_view),
    path('api/conversations/<uuid:chat_id>/save/', conversations.save_view),
    path('api/conversations/<uuid:chat_id>/trash/', conversations.trash_view),
    path('api/conversations/<uuid:chat_id>/restore/', conversations.restore_view),
    path('', views.app, name='app'),
    path('c/<uuid:chat_id>', views.app, name='conversation'),
    path('accounts/login/', LimitedLoginView.as_view(redirect_authenticated_user=True), name='login'),
    path('accounts/logout/', views.logout_view, name='logout'),
    path('api/status/', views.status_view),
    path('api/catalog/', views.catalog_view),
    path('api/chat/', views.chat_view),
    path('api/tracking/', views.tracking_view),
    path('api/dashboard/', views.dashboard_view),
    path('api/results/<uuid:job_id>/', views.result_view),
    path('api/results/<uuid:job_id>/cancel/', views.cancel_view),
    path('api/results/<uuid:job_id>/pdf/', views.pdf_view),
    path('api/results/<uuid:job_id>/csv/', views.export_view, {'extension': 'csv'}),
    path('api/results/<uuid:job_id>/xlsx/', views.export_view, {'extension': 'xlsx'}),
]
