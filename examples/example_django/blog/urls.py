from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from .views import ArticleListView, CommentFormView, save_state

urlpatterns = [
    path("", ArticleListView.as_view(), name="article-list"),
    path("comment", CommentFormView.as_view(), name="comment"),
    path("state/save", save_state, name="save-state"),
]
