from django.contrib.auth import get_user_model
from rest_framework import serializers

from users.models import TenantProfile

User = get_user_model()


class TenantProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantProfile
        fields = ("id", "freezed_at", "deleted_at", "keep_dedicated_gpus")
        read_only_fields = fields


class UserRegisterSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True)
    api_token = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("username", "email", "password", "api_token")

    def get_api_token(self, obj) -> str:
        return obj.auth_token.key

    def create(self, validated_data):
        # Create standard Django user
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
        )
        return user


class TenantUserSerializer(serializers.ModelSerializer):
    profile = TenantProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ("id", "username", "email", "profile")
        read_only_fields = fields
