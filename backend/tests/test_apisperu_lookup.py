import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException


os.environ["DATABASE_URL"] = "sqlite://"
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common
import r_auth


class LookupResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class ApisperuLookupTests(unittest.TestCase):
    def setUp(self):
        self.token_patch = patch.object(r_auth, "PERU_API_TOKEN", "unit-test-token")
        self.token_patch.start()
        self.addCleanup(self.token_patch.stop)

    def test_valid_dni_returns_only_name_and_document(self):
        with patch.object(r_auth, "http_json", return_value={
            "nombres": "Ana", "apellidoPaterno": "Pérez", "apellidoMaterno": "Lima", "extra": "ignored",
        }) as request:
            result = r_auth.lookup_dni("12345678", u=object())

        self.assertEqual(result, {"dni": "12345678", "name": "Ana Pérez Lima"})
        request.assert_called_once_with("https://dniruc.apisperu.com/api/v1/dni/12345678")

    def test_valid_ruc_returns_sanitized_fields(self):
        with patch.object(r_auth, "http_json", return_value={
            "razonSocial": "  COMERCIAL EJEMPLO S.A.C.  ",
            "direccion": "Av. Uno 123", "distrito": "Lima", "provincia": "Lima",
            "departamento": "Lima", "estado": "ACTIVO", "condicion": "HABIDO",
            "token": "must-not-be-returned",
        }) as request:
            result = r_auth.lookup_ruc("20123456789", u=object())

        self.assertEqual(result, {
            "ruc": "20123456789", "name": "COMERCIAL EJEMPLO S.A.C.",
            "address": "Av. Uno 123 Lima Lima Lima", "status": "ACTIVO", "condition": "HABIDO",
        })
        request.assert_called_once_with("https://dniruc.apisperu.com/api/v1/ruc/20123456789")

    def test_invalid_dni_and_ruc_are_rejected_before_external_call(self):
        with patch.object(r_auth, "http_json") as request:
            for value in ("1234567", "123456789", "1234 678", "１２３４５６７８"):
                with self.subTest(document=value), self.assertRaises(HTTPException) as caught:
                    r_auth.lookup_dni(value, u=object())
                self.assertEqual(caught.exception.status_code, 400)
            for value in ("1234567890", "123456789012", "12345abc789", " 20123456789"):
                with self.subTest(document=value), self.assertRaises(HTTPException) as caught:
                    r_auth.lookup_ruc(value, u=object())
                self.assertEqual(caught.exception.status_code, 400)
        request.assert_not_called()

    def test_absent_token_is_a_configuration_error_without_network_call(self):
        with patch.object(r_auth, "PERU_API_TOKEN", ""), patch.object(r_auth, "http_json") as request:
            with self.assertRaises(HTTPException) as caught:
                r_auth.lookup_dni("12345678", u=object())
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("no está configurada", caught.exception.detail)
        request.assert_not_called()

    def test_missing_document_is_a_not_found_response(self):
        with patch.object(r_auth, "http_json", return_value={"success": False}):
            with self.assertRaises(HTTPException) as caught:
                r_auth.lookup_ruc("20123456789", u=object())
        self.assertEqual(caught.exception.status_code, 404)

    def test_sales_and_supplier_manager_permissions_can_query_but_other_roles_cannot(self):
        authorize = r_auth.need_any("sales.create", "purchases.manage")
        cashier = SimpleNamespace(role="cajero", additional_role_links=[])
        supervisor = SimpleNamespace(role="supervisor", additional_role_links=[])
        warehouse = SimpleNamespace(role="almacen", additional_role_links=[])
        self.assertIs(authorize(u=cashier), cashier)
        self.assertIs(authorize(u=supervisor), supervisor)
        with self.assertRaises(HTTPException) as caught:
            authorize(u=warehouse)
        self.assertEqual(caught.exception.status_code, 403)

    def test_http_helper_sends_bearer_token_and_returns_json_without_logging_it(self):
        response = LookupResponse(json.dumps({"nombres": "Ana"}).encode("utf-8"))
        with patch.object(common, "PERU_API_TOKEN", "test-only-secret"), \
             patch.object(common.urllib.request, "urlopen", return_value=response) as urlopen:
            result = common.http_json("https://dniruc.apisperu.com/api/v1/dni/12345678")

        self.assertEqual(result, {"nombres": "Ana"})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-only-secret")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 8)

    def test_invalid_token_is_reported_without_echoing_credentials(self):
        error = urllib.error.HTTPError("https://dniruc.apisperu.com", 401, "unauthorized", {}, io.BytesIO())
        with patch.object(common.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(HTTPException) as caught:
                common.http_json("https://dniruc.apisperu.com/api/v1/dni/12345678")
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("test-only-secret", caught.exception.detail)

    def test_connection_and_unexpected_response_have_clear_errors(self):
        with patch.object(common.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(HTTPException) as caught:
                common.http_json("https://dniruc.apisperu.com/api/v1/dni/12345678")
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("conectar", caught.exception.detail)

        with patch.object(common.urllib.request, "urlopen", return_value=LookupResponse(b"[]")):
            with self.assertRaises(HTTPException) as caught:
                common.http_json("https://dniruc.apisperu.com/api/v1/dni/12345678")
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("inesperada", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
