import logging

import jwt
from social_core.backends.open_id_connect import OpenIdConnectAuth

from galaxy.model import UserAuthnzToken
from galaxy.model.db.user import User
from galaxy.model.db.role import Role
from galaxy.model.security import GalaxyRBACAgent

# Set up a temp logger for debugging auth
auth_log = logging.getLogger("auth_log")
auth_log.setLevel(logging.DEBUG)

# Add handler only if not already present
if not auth_log.handlers:
    fh = logging.FileHandler('auth_testing.log')
    formatter = logging.Formatter('%(asctime)s  - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    auth_log.addHandler(fh)


def add_roles(user: User = None, backend: OpenIdConnectAuth = None, social: UserAuthnzToken = None, **kwargs):
    access_token_encoded = social.extra_data.get("access_token")
    access_token_data = _decode_access_token(token_str=access_token_encoded, backend=backend)
    galaxy_roles: list[str] = [role for role in access_token_data["biocommons.org.au/roles"]
                               if role.lower().startswith("galaxy/")]
    auth_log.info(f"Roles from access token: {galaxy_roles}")
    existing_roles: list[Role] = user.all_roles()
    existing_names = [role.name for role in existing_roles]
    auth_log.info(f"Existing roles: {existing_names}")
    roles_to_add = []
    for role_name in galaxy_roles:
        if role_name not in existing_names:
            roles_to_add.append(role_name)
    auth_log.info(f"Roles to add: {roles_to_add}")

    rbac = GalaxyRBACAgent(sa_session=social.sa_session)
    for role_name in roles_to_add:
        auth_log.info(f"Adding role: {role_name} to user: {user.id}")
        role = (social.sa_session.query(Role)
                .filter_by(name=role_name).first())
        rbac.associate_user_role(user=user, role=role)


def _decode_access_token(token_str: str, backend: OpenIdConnectAuth) -> dict:
    signing_key = backend.find_valid_key(token_str)
    jwk = jwt.PyJWK(signing_key)
    auth_log.info(f"Signing token: {jwk}")
    decoded = jwt.decode(
        token_str,
        key=jwk,
        algorithms=[jwk.algorithm_name],
        # TODO: want to get audience from backend/config but not 100% sure if it's passed
        #   through currently
        audience="https://dev-bc.minh.com/api",
        issuer=backend.id_token_issuer(),
        options={"verify_signature": True, "verify_exp": True, "verify_aud": True},
    )
    return decoded
