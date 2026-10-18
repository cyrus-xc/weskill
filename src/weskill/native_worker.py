"""Private pipe protocol: establish Frida before accepting a business request."""
import json
import sys

from .backend import ExperimentalBackend, NativeConnectionTimeout


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=True) + '\n')
    sys.stdout.flush()


def main():
    config = json.loads(sys.stdin.readline())
    backend = ExperimentalBackend(config['pid'], config['shim_path'], config['state_dir'],
                                  config['allowed_recipients'])
    try:
        backend._ensure_session()
    except Exception as error:
        emit({'ready': False,
              'error_code': 'connection_timeout' if isinstance(error, NativeConnectionTimeout)
              else 'connection_failed', 'error': f'{type(error).__name__}: {error}'})
        return
    emit({'ready': True})
    for line in sys.stdin:
        request = json.loads(line)
        mode, values = request['mode'], request['parameters']
        try:
            if mode == 'search':
                response = backend.search_contacts(values['keywords'], values['limit'],
                                                   values['filter_type'] == 2)
            elif mode == 'messages':
                response = backend.get_messages(values['chat_ids'], values['limit'])
            elif mode == 'send':
                response = backend.send_text(values['recipient'], values['text'], request['id'])
            else:
                raise ValueError('Unsupported native operation')
        except Exception as error:
            response = {'status': 'unknown', 'result': None, 'delivery_confirmed': False,
                        'errors': [f'{type(error).__name__}: {error}']}
        emit({'id': request['id'], 'response': response})


if __name__ == '__main__':
    main()
