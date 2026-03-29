import 'package:dio/dio.dart';
import 'log_store.dart';

/// Dio interceptor that records structured logs to LogStore.
class AppLogInterceptor extends Interceptor {
  final LogStore _store;

  AppLogInterceptor(this._store);

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    options.extra['_startTime'] = DateTime.now().millisecondsSinceEpoch;
    handler.next(options);
  }

  @override
  void onResponse(Response response, ResponseInterceptorHandler handler) {
    final start = response.requestOptions.extra['_startTime'] as int? ?? 0;
    final duration = DateTime.now().millisecondsSinceEpoch - start;
    _store.add(LogEntry(
      time: DateTime.now(),
      method: response.requestOptions.method,
      url: _shortenUrl(response.requestOptions.path),
      statusCode: response.statusCode,
      durationMs: duration,
      level: 'info',
    ));
    handler.next(response);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final start = err.requestOptions.extra['_startTime'] as int? ?? 0;
    final duration = DateTime.now().millisecondsSinceEpoch - start;
    _store.add(LogEntry(
      time: DateTime.now(),
      method: err.requestOptions.method,
      url: _shortenUrl(err.requestOptions.path),
      statusCode: err.response?.statusCode,
      durationMs: duration,
      error: err.message ?? err.type.name,
      level: 'error',
    ));
    handler.next(err);
  }

  /// Strip base URL, keep path only.
  String _shortenUrl(String url) {
    if (url.startsWith('http')) {
      final uri = Uri.tryParse(url);
      return uri?.path ?? url;
    }
    return url;
  }
}
