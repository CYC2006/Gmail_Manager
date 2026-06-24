import os
import sys
import json
import time
import threading

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from flask import Flask, jsonify, request, render_template, Response, stream_with_context

from src.gmail_reader import (
    get_gmail_service, build_action_service,
    fetch_and_analyze_emails, fetch_simple_emails,
)
from src.email_actions import (
    mark_as_read, toggle_star, archive_email, unarchive_email,
    trash_email, restore_email, permanent_delete_email,
)
from src.db_manager import (
    get_cached_result, get_detail_analysis, save_detail_analysis, delete_analysis,
)
from src.email_parser import get_email_body
from src.ai_agent import analyze_email_detail, verify_api_key, reload_keys
from src.config_manager import (
    load_user_prefs, save_user_prefs,
    get_groq_api_keys, save_groq_api_keys,
    get_selected_interests, save_selected_interests,
)
from src.calendar_db import (
    init_calendar_db, add_custom_event, delete_event,
    delete_events_by_email_id, get_all_events,
)

app = Flask(__name__)
init_calendar_db()

_svc_lock = threading.Lock()
_svc = None

def get_service():
    global _svc
    with _svc_lock:
        if _svc is None:
            _svc = get_gmail_service()
        return _svc

_user_email = None
_user_email_lock = threading.Lock()

def get_cached_user_email():
    global _user_email
    with _user_email_lock:
        if _user_email is None:
            try:
                profile = get_service().users().getProfile(userId='me').execute()
                _user_email = profile.get('emailAddress', '')
            except Exception:
                _user_email = ''
        return _user_email


# ── Page ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ── User ────────────────────────────────────────────────────────────────────

@app.route('/api/user')
def api_user():
    return jsonify({'email': get_cached_user_email()})


# ── Email streaming (SSE) ────────────────────────────────────────────────────

@app.route('/api/emails/stream')
def stream_emails():
    view = request.args.get('view', 'inbox')

    def generate():
        try:
            svc = get_service()
            if svc is None:
                yield f"event: error\ndata: {json.dumps({'error': 'Not authenticated'})}\n\n"
                return

            if view == 'trash':
                for email in fetch_simple_emails(svc, 'in:trash'):
                    if '_next_page_token' not in email:
                        yield f"data: {json.dumps(email)}\n\n"
            else:
                # Stream emails across pages; client-side splits into inbox/moodle/all_mail
                page_token = None
                for _ in range(10):  # max 10 pages = 500 emails
                    has_more = False
                    for email in fetch_and_analyze_emails(svc, page_token=page_token):
                        if '_next_page_token' in email:
                            page_token = email['_next_page_token']
                            has_more = True
                        else:
                            yield f"data: {json.dumps(email)}\n\n"
                    if not has_more:
                        break

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

        yield "event: done\ndata: {}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# ── Email detail ─────────────────────────────────────────────────────────────

@app.route('/api/email/<email_id>/body')
def api_email_body(email_id):
    try:
        svc = build_action_service()
        msg = svc.users().messages().get(userId='me', id=email_id, format='full').execute()
        body = get_email_body(msg.get('payload', {}))
        return jsonify({'body': body})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/analyze')
def api_analyze(email_id):
    try:
        cached = get_detail_analysis(email_id)
        if cached:
            print(f"[ANALYZE] Cache hit for {email_id}")
            return jsonify(cached)
        svc = build_action_service()
        msg = svc.users().messages().get(userId='me', id=email_id, format='full').execute()
        body = get_email_body(msg.get('payload', {}))
        print(f"[ANALYZE] email_id={email_id} body_len={len(body) if body else 0} body_preview={repr(body[:120]) if body else 'EMPTY'}")
        meta = get_cached_result(email_id)
        category = meta.get('category') if meta else None
        result = analyze_email_detail(body, category=category)
        if result is None:
            print("[ANALYZE] First attempt returned None — retrying in 3s")
            time.sleep(3)
            result = analyze_email_detail(body, category=category)
        if result:
            save_detail_analysis(email_id, result)
            return jsonify(result)
        print("[ANALYZE] Both attempts failed — returning _failed")
        return jsonify({'_failed': True})
    except Exception as e:
        print(f"[ANALYZE] Exception: {e}")
        return jsonify({'error': str(e)}), 500


# ── Email actions ─────────────────────────────────────────────────────────────

@app.route('/api/email/<email_id>/mark_read', methods=['POST'])
def api_mark_read(email_id):
    try:
        mark_as_read(build_action_service(), email_id)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/star', methods=['POST'])
def api_star(email_id):
    try:
        data = request.get_json() or {}
        toggle_star(build_action_service(), email_id, data.get('starred', True))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/archive', methods=['POST'])
def api_archive(email_id):
    try:
        archive_email(build_action_service(), email_id)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/unarchive', methods=['POST'])
def api_unarchive(email_id):
    try:
        unarchive_email(build_action_service(), email_id)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/trash', methods=['POST'])
def api_trash(email_id):
    try:
        trash_email(build_action_service(), email_id)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/restore', methods=['POST'])
def api_restore(email_id):
    try:
        restore_email(build_action_service(), email_id)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/email/<email_id>/delete', methods=['POST'])
def api_delete(email_id):
    try:
        permanent_delete_email(build_action_service(), email_id)
        delete_analysis(email_id)
        delete_events_by_email_id(email_id)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Calendar ──────────────────────────────────────────────────────────────────

@app.route('/api/calendar/events')
def api_calendar_get():
    try:
        return jsonify(get_all_events())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/calendar/events', methods=['POST'])
def api_calendar_create():
    try:
        d = request.get_json() or {}
        add_custom_event(
            date_key=d.get('date_key', ''),
            title=d.get('title', ''),
            start_time=d.get('start_time', ''),
            end_time=d.get('end_time', ''),
            is_all_day=d.get('is_all_day', False),
            color=d.get('color', ''),
            notes=d.get('notes', ''),
        )
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/calendar/events/<int:event_id>', methods=['DELETE'])
def api_calendar_delete(event_id):
    try:
        delete_event(event_id)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Settings ──────────────────────────────────────────────────────────────────

SETTINGS_PATH = os.path.join(PROJECT_ROOT, 'data', 'web_settings.json')

_web_settings_cache = None
_web_settings_lock  = threading.Lock()

def _load_web_settings():
    global _web_settings_cache
    with _web_settings_lock:
        if _web_settings_cache is not None:
            return dict(_web_settings_cache)
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH) as f:
                _web_settings_cache = json.load(f)
        else:
            _web_settings_cache = {}
        return dict(_web_settings_cache)

def _save_web_settings(s):
    global _web_settings_cache
    with _web_settings_lock:
        with open(SETTINGS_PATH, 'w') as f:
            json.dump(s, f, indent=2)
        _web_settings_cache = dict(s)


@app.route('/api/settings/theme')
def api_get_theme():
    return jsonify({'theme': _load_web_settings().get('theme', 'dark')})


@app.route('/api/settings/theme', methods=['POST'])
def api_set_theme():
    try:
        d = request.get_json() or {}
        s = _load_web_settings()
        s['theme'] = d.get('theme', 'dark')
        _save_web_settings(s)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/options')
def api_settings_options():
    try:
        opts_path = os.path.join(PROJECT_ROOT, 'src', 'settings', 'preference_options.json')
        with open(opts_path, encoding='utf-8') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/profile')
def api_get_profile():
    p = load_user_prefs()
    return jsonify({
        'name':   p.get('user_name', ''),
        'gender': p.get('user_gender', ''),
        'major':  p.get('selected_major', ''),
        'gmail':  p.get('gmail_account', ''),
    })


@app.route('/api/settings/profile', methods=['POST'])
def api_save_profile():
    try:
        d = request.get_json() or {}
        p = load_user_prefs()
        p['user_name']     = d.get('name', p.get('user_name', ''))
        p['user_gender']   = d.get('gender', p.get('user_gender', ''))
        p['selected_major'] = d.get('major', p.get('selected_major', ''))
        p['gmail_account'] = d.get('gmail', p.get('gmail_account', ''))
        save_user_prefs(p)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/interests')
def api_get_interests():
    return jsonify({'interests': get_selected_interests()})


@app.route('/api/settings/interests', methods=['POST'])
def api_save_interests():
    try:
        d = request.get_json() or {}
        save_selected_interests(d.get('interests', []))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/api-keys')
def api_get_keys():
    keys = get_groq_api_keys()
    return jsonify({'keys': keys if keys else ['']})


@app.route('/api/settings/api-keys', methods=['POST'])
def api_save_keys():
    try:
        d = request.get_json() or {}
        keys = [k.strip() for k in d.get('keys', []) if k.strip()]
        results = []
        for key in keys:
            status = verify_api_key(key)
            results.append({'key': key, 'status': status})
        verified = [r['key'] for r in results if r['status'] == 'verified']
        save_groq_api_keys(verified)
        reload_keys()
        return jsonify({'ok': True, 'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/api-keys/verify', methods=['POST'])
def api_verify_key():
    try:
        d = request.get_json() or {}
        key = d.get('key', '').strip()
        return jsonify({'status': verify_api_key(key)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/debug/ai')
def api_debug_ai():
    """Diagnostic endpoint — tests Groq connectivity with a minimal prompt."""
    from src.ai_agent import _AVAILABLE_KEYS, TPD_EXHAUSTED, _call_groq
    n_keys = len(_AVAILABLE_KEYS)
    test_raw = None
    test_error = None
    try:
        test_raw = _call_groq(
            messages=[{"role": "user", "content": "Reply with exactly: {\"ok\": true}"}],
            max_tokens=20,
        )
    except Exception as e:
        test_error = str(e)
    return jsonify({
        'n_keys': n_keys,
        'TPD_EXHAUSTED': TPD_EXHAUSTED,
        'test_raw': test_raw,
        'test_error': test_error,
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, port=port, threaded=True)
