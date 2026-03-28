import 'dart:io';
import 'package:dio/dio.dart';
import 'env.dart';
import 'auth_interceptor.dart';
import '../storage/secure_storage.dart';

/// Creates a configured Dio instance with auth interceptor.
/// Trusts self-signed certs (Tailscale HTTPS) via custom HttpClient.
Dio createDio(SecureStorage storage, {String? baseUrl}) {
  final dio = Dio(BaseOptions(
    baseUrl: baseUrl ?? AppEnv.defaultBaseUrl,
    connectTimeout: AppEnv.connectTimeout,
    receiveTimeout: AppEnv.receiveTimeout,
    headers: {'Content-Type': 'application/json'},
  ));

  // Only trust self-signed certs for the configured Tailscale host
  final trustedHost = Uri.parse(baseUrl ?? AppEnv.defaultBaseUrl).host;
  (dio.httpClientAdapter as dynamic).onHttpClientCreate =
      (HttpClient client) {
    client.badCertificateCallback = (cert, host, port) =>
        host == trustedHost;
    return client;
  };

  dio.interceptors.add(AuthInterceptor(storage));
  return dio;
}
