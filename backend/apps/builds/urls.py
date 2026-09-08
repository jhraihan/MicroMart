from django.urls import path

from . import views

app_name = "builds"

urlpatterns = [
    # The builder's own vocabulary, served rather than duplicated client-side.
    path("pc-builder/slots/", views.SlotListView.as_view(), name="slots"),
    # The catalogue side: what can go in a slot, narrowed by what is chosen.
    path("pc-builder/components/", views.ComponentListView.as_view(), name="components"),
    # Stateless check. Nothing is written, so the panel can revalidate freely.
    path("pc-builder/validate/", views.BuildValidateView.as_view(), name="validate"),
    path("builds/", views.BuildListCreateView.as_view(), name="build-list"),
    path("builds/<str:token>/", views.BuildDetailView.as_view(), name="build-detail"),
]
