import os
from datetime import datetime

from aleph_client.asynchronous import create_store
from aleph_client.chains.remote import RemoteAccount
from django.conf import settings
from django.http import JsonResponse
from django.views.generic import ListView, CreateView

from .forms import CommentForm
from .models import Article


class ArticleListView(ListView):
    model = Article
    ordering = "-date"

    extra_context = {"form": CommentForm}


class CommentFormView(CreateView):
    template_name = "blog/comment.html"
    form_class = CommentForm
    success_url = "/"


async def save_state(request):
    db_path: str = settings.DATABASES['default']['NAME']
    with open(db_path, 'rb') as db_file:
        content: bytes = db_file.read()

    account = await RemoteAccount.from_crypto_host(
        host="http://localhost", unix_socket="/tmp/socat-socket")

    response = await create_store(
        account=account,
        file_content=content,
        ref=None,
        channel="TEST",
        storage_engine="storage",
    )
    print(response)
    return JsonResponse({'hello': 'world'})
