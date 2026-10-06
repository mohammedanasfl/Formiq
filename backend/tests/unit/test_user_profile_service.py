from app.models import UserProfile
from app.schemas import UserProfileUpdate
from app.services.user_profile_service import REQUIRED_PROFILE_FIELDS


def test_required_profile_fields_are_the_not_null_updatable_columns():
    not_null_columns = {
        column.name for column in UserProfile.__table__.columns if not column.nullable
    }

    assert REQUIRED_PROFILE_FIELDS == not_null_columns & set(UserProfileUpdate.model_fields)
