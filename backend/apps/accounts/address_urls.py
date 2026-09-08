"""Address book routes, mounted at /api/v1/addresses/ (PRD 7.2)."""
from rest_framework.routers import DefaultRouter

from . import views

app_name = "addresses"

router = DefaultRouter()
router.register("addresses", views.AddressViewSet, basename="address")

urlpatterns = router.urls
