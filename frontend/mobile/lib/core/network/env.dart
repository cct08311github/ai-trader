/// App configuration — base URL and timeouts.
class AppEnv {
  static const defaultBaseUrl = 'https://mac-mini.tailde842d.ts.net:8080';
  static const connectTimeout = Duration(seconds: 10);
  static const receiveTimeout = Duration(seconds: 15);
  static const batchTimeout = Duration(seconds: 20);
}
