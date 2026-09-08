"""
Review moderation routes for the admin surface (PRD 7.3).

Included under admin/ from config/api_urls.py, so these resolve as
/api/v1/admin/reviews/ and /api/v1/admin/reviews/{id}/moderate/.

**Why they are not in apps/dashboard/urls.py**: that module is still an empty
stub with zero routes -- the admin surface is not being assembled there yet.
Putting the first admin endpoints inside the app that owns their models keeps
them next to the services they call, and dashboard/urls.py can absorb them
later by including this module instead. Both are already mounted at admin/,
so moving them would not change a single URL.
"""
from django.urls import path

from . import views

app_name = "reviews_admin"

urlpatterns = [
    path("reviews/", views.AdminReviewListView.as_view(), name="review-list"),
    path(
        "reviews/<int:pk>/moderate/",
        views.AdminReviewModerateView.as_view(),
        name="review-moderate",
    ),
]
