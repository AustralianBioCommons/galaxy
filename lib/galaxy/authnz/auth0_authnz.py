import logging
from typing import Any

import jwt
from social_core.backends.open_id_connect import OpenIdConnectAuth

from galaxy.model import UserAuthnzToken, UserRoleAssociation
from galaxy.model.db.user import User
from galaxy.model.db.role import Role
from galaxy.model.security import GalaxyRBACAgent

ROLE_PREFIX = "galaxy/"

# Set up a temp logger for debugging auth
auth_log = logging.getLogger("auth_log")
auth_log.setLevel(logging.DEBUG)

# Add handler only if not already present
if not auth_log.handlers:
    fh = logging.FileHandler('auth_testing.log')
    formatter = logging.Formatter('%(asctime)s  - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    auth_log.addHandler(fh)


def decode_access_token(social: UserAuthnzToken, backend: OpenIdConnectAuth, **kwargs):
    """
    Decode the access token and add it to the 'social' data as
    a new argument "access_token" that can be used in future pipeline steps

    Depends on "access_token" being present in social.extra_data,
    which should be handled by social_core.pipeline.social_auth.load_extra_data
    """
    access_token_encoded = social.extra_data.get("access_token")
    access_token_data = _decode_access_token(token_str=access_token_encoded, backend=backend)
    return {"access_token": access_token_data}


def add_roles(user: User = None, access_token: dict[str, Any] = None, social: UserAuthnzToken = None, **kwargs):
    """
    Add roles for the current user based on the roles
    in access_token["biocommons.org.au/roles"]

    Depends on access_token data being available as a pipeline argument:
    currently handled by the decode_access_token step
    """
    # TODO: make the claim name for the roles, and the prefix for the
    #  roles to be added, configurable
    token_roles: list[str] = [role for role in access_token["biocommons.org.au/roles"]
                               if role.lower().startswith(ROLE_PREFIX)]
    auth_log.info(f"Roles from access token: {token_roles}")
    # TODO: all the querying and db operations here can definitely
    #   be done more efficiently, but want to make sure the
    #   logic is clear to start with
    # Only look at roles beginning with ROLE_PREFIX - others are not
    #   managed via OIDC
    existing_roles: list[Role] = [role for role in user.all_roles()
                                  if role.name.lower().startswith(ROLE_PREFIX)]
    existing_names = [role.name for role in existing_roles]
    auth_log.info(f"Existing roles: {existing_names}")
    roles_to_add = []
    for role_name in token_roles:
        if role_name not in existing_names:
            roles_to_add.append(role_name)
    auth_log.info(f"Roles to add: {roles_to_add}")
    roles_to_remove = []
    for role in existing_roles:
        if role.name not in token_roles:
            roles_to_remove.append(role)

    rbac = GalaxyRBACAgent(sa_session=social.sa_session)
    for role_name in roles_to_add:
        auth_log.info(f"Adding role: {role_name} to user: {user.id}")
        role = (social.sa_session.query(Role)
                .filter_by(name=role_name).first())
        if role is not None:
            rbac.associate_user_role(user=user, role=role)
        else:
            auth_log.warning(f"Role {role_name} not found - currently only existing roles are added")

    for role in roles_to_remove:
        assoc = social.sa_session.query(UserRoleAssociation).filter_by(role_id=role.id, user_id=user.id)
        assoc.delete()
        social.sa_session.commit()


def _decode_access_token(token_str: str, backend: OpenIdConnectAuth) -> dict:
    """
    Decode the access token (verifying that signature, expiry and
    audience are valid)
    """
    signing_key = backend.find_valid_key(token_str)
    jwk = jwt.PyJWK(signing_key)
    auth_log.info(f"Signing token: {jwk}")
    auth_log.info(f"{backend.strategy.config['accepted_audiences']=}")
    decoded = jwt.decode(
        token_str,
        key=jwk,
        algorithms=[jwk.algorithm_name],
        audience=backend.strategy.config["accepted_audiences"],
        issuer=backend.id_token_issuer(),
        options={"verify_signature": True, "verify_exp": True, "verify_aud": True},
    )
    # NOTE: could try to validate at_hash here but it should already be handled
    #   by python-social-auth, and python-social-auth doesn't seem to like
    #   fetching the id token again as it interferes with the nonce
    return decoded
