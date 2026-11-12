"""DELIBERATELY VULNERABLE training target. Runs only inside the isolated gotham-lab network.
GOTHAM_LAB_SECURE=1 switches on the remediated behaviour so fixes can be verified."""
import html, os, sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

SECURE = os.environ.get('GOTHAM_LAB_SECURE') == '1'
db = sqlite3.connect(':memory:', check_same_thread=False)
db.execute('create table users(name text, pw text)')
db.execute("insert into users values('admin','s3cr3t-lab-only')")
FILES = '/app/files/'


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, code=200, ctype='text/html'):
        b = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        if SECURE:
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'")
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == '/health':
            return self.send('ok', ctype='text/plain')
        if u.path == '/login':
            user, pw = q.get('user', ''), q.get('pw', '')
            if SECURE:
                row = db.execute('select 1 from users where name=? and pw=?', (user, pw)).fetchone()
            else:
                try:
                    row = db.execute("select 1 from users where name='%s' and pw='%s'" % (user, pw)).fetchone()
                except sqlite3.Error:
                    row = None
            return self.send('WELCOME admin' if row else 'denied')
        if u.path == '/file':
            name = q.get('name', '')
            path = os.path.realpath(os.path.join(FILES, name))
            if SECURE and not path.startswith(FILES):
                return self.send('forbidden', 403)
            try:
                return self.send(open(path if SECURE else FILES + name).read(), ctype='text/plain')
            except OSError:
                return self.send('not found', 404)
        if u.path == '/search':
            term = q.get('q', '')
            return self.send('<p>Results for: ' + (html.escape(term) if SECURE else term) + '</p>')
        self.send('lab', 200)


HTTPServer(('0.0.0.0', 8080), H).serve_forever()
