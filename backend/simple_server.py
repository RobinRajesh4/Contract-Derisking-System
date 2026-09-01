from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Hello World')

if __name__ == "__main__":
    server = HTTPServer(('0.0.0.0', 8002), Handler)
    print('Starting simple HTTP server on port 8002')
    server.serve_forever()