import base64
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import jwt
# Tools from hazmat should only be used for testing!
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from jwt import InvalidIssuerError, InvalidAudienceError, InvalidSignatureError

from galaxy.authnz.auth0_authnz import decode_access_token
from galaxy.util.unittest import TestCase


@dataclass
class AuthTokenData:
    private_key: RSAPrivateKey
    public_key: RSAPublicKey
    access_token_str: str
    access_token_data: dict
    key_id: str


def create_access_token(
        email: str = "user@example.com",
        roles: list[str] = None,
        iss: str = "https://biocommons.au.auth0.com",
        sub: str = None,
        iat: int = None,
        exp: int = None,
        aud: str = "https://galaxy.biocommons.org.au",
        scope: list[str] = None,
        azp: str = None,
        permissions: list[str] = None,
        algorithm: str = "RS256",
        public_key_id: str = "example-key",
) -> AuthTokenData:
    """
    Create an OIDC access token along with a dummy private and public key
    for signing it. Each field of the payload can be set, but otherwise
    will get a sensible default (e.g. expiry time in the future).
    """
    if roles is None:
        roles = []
    if sub is None:
        sub = f"auth0|{uuid.uuid4().hex}"
    if iat is None:
        iat = int(datetime.now().strftime("%s"))
    if exp is None:
        exp = int((datetime.now() + timedelta(hours=1)).strftime("%s"))
    if azp is None:
        azp = uuid.uuid4().hex
    if permissions is None:
        permissions = []

    payload = {
        "email": email,
        "biocommons.org.au/roles": roles,
        "iss": iss,
        "sub": sub,
        "aud": [aud],
        "iat": iat,
        "exp": exp,
        "scope": scope,
        "azp": azp,
        "permissions": permissions,
    }
    public_key, private_key = generate_public_private_key_pair()
    access_token_encoded = jwt.encode(
        payload,
        key=private_key,
        algorithm=algorithm,
        headers={"kid": public_key_id},
    )
    return AuthTokenData(
        private_key=private_key,
        public_key=public_key,
        access_token_str=access_token_encoded,
        access_token_data=payload,
        key_id=public_key_id
    )


def generate_public_private_key_pair():
    # Code from https://fmpm.dev/mocking-auth0-tokens
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return public_key, private_key


def get_jwk_data(public_key: RSAPublicKey):
    """
    Format an RSAPublicKey into the structure PyJWK expects.
    """
    def base64url_uint(val: int) -> str:
        """Base64url encode a big integer."""
        b = val.to_bytes((val.bit_length() + 7) // 8, 'big')
        return base64.urlsafe_b64encode(b).rstrip(b'=').decode('ascii')
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "n": base64url_uint(numbers.n),
        "e": base64url_uint(numbers.e)
    }


class TestAuth0Authnz(TestCase):
    """
    Test how we handle access tokens. Because our handling code
    occurs at the end of a complex social-auth pipeline, we use
    mock objects (e.g. mocking the social-auth backend) to inject
    required data into the functions
    """

    def test_decode_access_token(self):
        """
        Test we can decode a valid access token.
        """
        dummy_access_token = create_access_token()
        mock_social = MagicMock()
        mock_social.extra_data.get.return_value = dummy_access_token.access_token_str
        mock_backend = MagicMock()
        public_key_data = get_jwk_data(dummy_access_token.public_key)
        mock_backend.find_valid_key.return_value = public_key_data
        mock_backend.strategy.config = {"accepted_audiences": dummy_access_token.access_token_data["aud"]}
        mock_backend.id_token_issuer.return_value = dummy_access_token.access_token_data["iss"]
        data = decode_access_token(social=mock_social, backend=mock_backend)
        assert data["access_token"] == dummy_access_token.access_token_data

    def test_decode_access_token_invalid_key(self):
        """
        Test that decoding fails when an invalid key is provided.
        """
        dummy_access_token = create_access_token()
        incorrect_public_key, incorrect_private_key = generate_public_private_key_pair()
        mock_social = MagicMock()
        mock_social.extra_data.get.return_value = dummy_access_token.access_token_str
        mock_backend = MagicMock()
        incorrect_public_key_data = get_jwk_data(incorrect_public_key)
        mock_backend.find_valid_key.return_value = incorrect_public_key_data
        mock_backend.strategy.config = {"accepted_audiences": dummy_access_token.access_token_data["aud"]}
        mock_backend.id_token_issuer.return_value = dummy_access_token.access_token_data["iss"]
        with self.assertRaises(InvalidSignatureError):
            data = decode_access_token(social=mock_social, backend=mock_backend)

    def test_decode_access_token_invalid_issuer(self):
        """
        Test that a token with an invalid issuer (doesn't match what we expect) raises
        an error
        """
        dummy_access_token = create_access_token(iss="https://invalid.url")
        mock_social = MagicMock()
        mock_social.extra_data.get.return_value = dummy_access_token.access_token_str
        mock_backend = MagicMock()
        public_key_data = get_jwk_data(dummy_access_token.public_key)
        mock_backend.find_valid_key.return_value = public_key_data
        mock_backend.strategy.config = {"accepted_audiences": dummy_access_token.access_token_data["aud"]}
        mock_backend.id_token_issuer.return_value = "https://validissuer.com"
        with self.assertRaises(InvalidIssuerError):
            data = decode_access_token(social=mock_social, backend=mock_backend)

    def test_decode_access_token_invalid_audience(self):
        """
        Test that a token with an invalid audience (doesn't match what we expect) raises
        an error
        """
        dummy_access_token = create_access_token(aud="https://invalidaudience.url")
        mock_social = MagicMock()
        mock_social.extra_data.get.return_value = dummy_access_token.access_token_str
        mock_backend = MagicMock()
        public_key_data = get_jwk_data(dummy_access_token.public_key)
        mock_backend.find_valid_key.return_value = public_key_data
        mock_backend.strategy.config = {"accepted_audiences": ["https://validaudience.url"]}
        mock_backend.id_token_issuer.return_value = dummy_access_token.access_token_data["iss"]
        with self.assertRaises(InvalidAudienceError):
            data = decode_access_token(social=mock_social, backend=mock_backend)
