import 'dart:collection';
import 'package:flutter/foundation.dart';

/// Single log entry from Dio interceptor.
class LogEntry {
  final DateTime time;
  final String method;
  final String url;
  final int? statusCode;
  final int durationMs;
  final String? error;
  final String level; // info, warn, error

  LogEntry({
    required this.time,
    required this.method,
    required this.url,
    this.statusCode,
    required this.durationMs,
    this.error,
    required this.level,
  });

  String get summary {
    final status = statusCode != null ? '$statusCode' : 'ERR';
    final dur = '${durationMs}ms';
    final err = error != null ? ' — $error' : '';
    return '[$level] $method $url → $status ($dur)$err';
  }
}

/// Ring buffer of log entries with ChangeNotifier for UI binding.
class LogStore extends ChangeNotifier {
  static const maxEntries = 200;
  final Queue<LogEntry> _entries = Queue();

  List<LogEntry> get entries => _entries.toList();
  int get length => _entries.length;

  void add(LogEntry entry) {
    if (_entries.length >= maxEntries) {
      _entries.removeFirst();
    }
    _entries.addLast(entry);
    // Also print to console for debug builds
    debugPrint(entry.summary);
    notifyListeners();
  }

  void clear() {
    _entries.clear();
    notifyListeners();
  }
}
