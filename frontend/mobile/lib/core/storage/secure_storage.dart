import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Wrapper around flutter_secure_storage for auth token.
class SecureStorage {
  static const _tokenKey = 'auth_token';
  static const _baseUrlKey = 'base_url';
  final _storage = const FlutterSecureStorage();

  Future<String?> getToken() => _storage.read(key: _tokenKey);
  Future<void> setToken(String token) =>
      _storage.write(key: _tokenKey, value: token);
  Future<void> clearToken() => _storage.delete(key: _tokenKey);

  Future<String?> getBaseUrl() => _storage.read(key: _baseUrlKey);
  Future<void> setBaseUrl(String url) =>
      _storage.write(key: _baseUrlKey, value: url);
}
