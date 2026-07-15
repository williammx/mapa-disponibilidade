from app_v1.permissions import user_can_access_org, user_can_manage_org
from models import Membership, User


class FakeQuery:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.value


class FakeDb:
    def __init__(self, membership=None):
        self.membership = membership

    def query(self, _model):
        return FakeQuery(self.membership)


def test_platform_roles_can_manage_any_org():
    user = User(name="Admin", email="admin@example.com", password_hash="x", platform_role="platform_admin")

    assert user_can_access_org(FakeDb(), user, "org")
    assert user_can_manage_org(FakeDb(), user, "org")


def test_client_admin_can_manage_own_org():
    user = User(id="user", name="Client", email="client@example.com", password_hash="x", platform_role="none")
    membership = Membership(user_id="user", organization_id="org", role="client_admin")

    assert user_can_access_org(FakeDb(membership), user, "org")
    assert user_can_manage_org(FakeDb(membership), user, "org")
