import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../providers/core_providers.dart';

class LoginScreen extends ConsumerStatefulWidget {
  final VoidCallback onLoginSuccess;
  const LoginScreen({super.key, required this.onLoginSuccess});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _tokenController = TextEditingController();
  final _urlController = TextEditingController();
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _urlController.text = 'https://mac-mini.tailde842d.ts.net:8080';
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadSavedUrl());
  }

  Future<void> _loadSavedUrl() async {
    final storage = ref.read(storageProvider);
    final saved = await storage.getBaseUrl();
    if (saved != null && saved.isNotEmpty) {
      _urlController.text = saved;
    }
    final token = await storage.getToken();
    if (token != null && token.isNotEmpty) {
      _tokenController.text = token;
    }
  }

  Future<void> _login() async {
    final token = _tokenController.text.trim();
    final url = _urlController.text.trim();
    if (token.isEmpty) {
      setState(() => _error = '請輸入 Bearer Token');
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final storage = ref.read(storageProvider);
      await storage.setToken(token);
      if (url.isNotEmpty) {
        await storage.setBaseUrl(url);
        ref.read(baseUrlProvider.notifier).state = url;
      }
      ref.read(authTokenProvider.notifier).state = token;
      widget.onLoginSuccess();
    } catch (e) {
      setState(() => _error = '登入���敗：$e');
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.show_chart, size: 64, color: Color(0xFF10B981)),
              const SizedBox(height: 16),
              const Text(
                'AI Trader',
                style: TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.bold,
                    color: Colors.white),
              ),
              const SizedBox(height: 8),
              const Text('行動版儀表板',
                  style: TextStyle(fontSize: 14, color: Colors.white54)),
              const SizedBox(height: 40),
              TextField(
                controller: _urlController,
                style: const TextStyle(color: Colors.white, fontSize: 13),
                decoration: _inputDeco('Server URL'),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _tokenController,
                obscureText: true,
                style: const TextStyle(color: Colors.white, fontSize: 13),
                decoration: _inputDeco('Bearer Token (AUTH_TOKEN)'),
                onSubmitted: (_) => _login(),
              ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(_error!,
                      style:
                          const TextStyle(color: Colors.redAccent, fontSize: 12)),
                ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                height: 48,
                child: ElevatedButton(
                  onPressed: _loading ? null : _login,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF10B981),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12)),
                  ),
                  child: _loading
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.white))
                      : const Text('登入',
                          style: TextStyle(
                              fontSize: 16, fontWeight: FontWeight.w600)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  InputDecoration _inputDeco(String label) => InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: Colors.white38, fontSize: 13),
        filled: true,
        fillColor: const Color(0xFF1E293B),
        border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: BorderSide.none),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      );
}
