#!/usr/bin/env python3

import os
import sys
import hashlib
import socket
import time
import http.client
import ssl
from urllib.parse import urlparse
from pathlib import Path

CACHE_DIR = "/tmp/proxy_cache"
PORT = 3000
BACKEND = ""
DEBUG = False
CACHE_TTL = 300  

def debug(message):
    if DEBUG:
        timestamp = time.strftime("%H:%M:%S")
        print(f"[DEBUG] {timestamp} - {message}", file=sys.stderr, flush=True)

def parse_args():
    global PORT, BACKEND, CACHE_DIR, CACHE_TTL
    debug(f"Raw command line arguments: {sys.argv}")
    args = sys.argv[1:]
    while args:
        arg = args.pop(0)
        if arg == "--port":
            PORT = int(args.pop(0))
            debug(f"Setting port to {PORT}")
        elif arg == "--backend":
            BACKEND = args.pop(0)
            debug(f"Setting backend to {BACKEND}")
        elif arg == "--cache-dir":
            CACHE_DIR = args.pop(0)
            debug(f"Setting cache directory to {CACHE_DIR}")
        elif arg == "--ttl":
            CACHE_TTL = int(args.pop(0))
            debug(f"Setting cache TTL to {CACHE_TTL} seconds")
        elif arg == "--clear":
            debug("Clearing cache directory")
            for item in Path(CACHE_DIR).glob("*"):
                debug(f"Removing cache file: {item}")
                item.unlink()
            print("Cache cleared.")
            sys.exit(0)
        else:
            debug(f"Unknown option encountered: {arg}")
            print(f"Unknown option: {arg}")
            sys.exit(1)
    
    if not BACKEND:
        debug("Backend not specified - exiting")
        print("Error: --backend is required")
        sys.exit(1)
    
    debug(f"Final configuration - PORT: {PORT}, BACKEND: {BACKEND}, CACHE_DIR: {CACHE_DIR}, TTL: {CACHE_TTL}s")
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    os.chmod(CACHE_DIR, 0o700)
    debug(f"Cache directory {CACHE_DIR} created/verified")

def make_request(url, request_headers={}):
    debug(f"Making request to {url}")
    parsed_url = urlparse(url)
    
    # Filter and modify headers appropriately
    filtered_headers = {
        k: v for k, v in request_headers.items()
        if k.lower() not in ['host', 'connection', 'cache-control']
    }
    
    # Set proper Host header for the backend
    filtered_headers['Host'] = parsed_url.netloc
    
    debug(f"Final request headers: {filtered_headers}")
    
    start_time = time.time()
    conn = None
    try:
        if parsed_url.scheme == 'https':
            debug("Establishing HTTPS connection")
            context = ssl.create_default_context()
            conn = http.client.HTTPSConnection(parsed_url.netloc, context=context)
        else:
            debug("Establishing HTTP connection")
            conn = http.client.HTTPConnection(parsed_url.netloc)
        
        path = parsed_url.path or '/'
        if parsed_url.query:
            path += '?' + parsed_url.query
        
        debug(f"Final request path: {path}")
        conn.request("GET", path, headers=filtered_headers)
        
        response = conn.getresponse()
        debug(f"Response status: {response.status}")
        
        # Read all headers except those we want to filter
        headers = {
            k: v for k, v in response.getheaders()
            if k.lower() not in ['connection', 'keep-alive', 'transfer-encoding']
        }
        debug(f"Response headers received: {headers}")
        
        body = response.read()
        debug(f"Response body length: {len(body)} bytes")
        debug(f"Request completed in {time.time() - start_time:.3f} seconds")
        
        return response.status, headers, body
        
    except Exception as e:
        debug(f"Request failed with error: {str(e)}")
        raise
    finally:
        if conn:
            conn.close()
            debug("Connection closed")

def handle_request(request):
    debug(f"Raw request received:\n{request}")
    
    try:
        lines = [line.strip() for line in request.split('\n') if line.strip()]
        first_line = lines[0]
        debug(f"First line of request: {first_line}")
        
        parts = first_line.split()
        if len(parts) < 2:
            raise ValueError("Invalid request line")
            
        method = parts[0]
        path = parts[1]
        debug(f"Parsed method: {method}, path: {path}")
        
        # Parse headers from request
        headers = {}
        for line in lines[1:]:
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip()] = value.strip()
                debug(f"Header found: {key.strip()}: {value.strip()}")
        
        url = f"{BACKEND.rstrip('/')}{path}"
        debug(f"Constructed backend URL: {url}")
        
        if method != "GET":
            debug(f"Unsupported method {method} received")
            return "HTTP/1.1 405 Method Not Allowed\r\n\r\n405 Method Not Allowed"

        cache_key = hashlib.md5(url.encode()).hexdigest()
        cache_file = Path(CACHE_DIR) / cache_key
        debug(f"Cache key: {cache_key}, cache file: {cache_file}")

        # Check cache
        if cache_file.exists():
            debug("Cache file exists - checking validity")
            cache_stat = cache_file.stat()
            debug(f"Cache file stats: size={cache_stat.st_size} bytes, mtime={time.ctime(cache_stat.st_mtime)}")
            
            # Check if cache is stale
            if time.time() - cache_stat.st_mtime > CACHE_TTL:
                debug("Cache is stale - refreshing")
                cache_file.unlink()
            else:
                try:
                    with cache_file.open('rb') as f:
                        status_line = f.readline().decode().strip()
                        debug(f"Cached status line: {status_line}")
                        
                        headers = {}
                        while True:
                            line = f.readline().decode().strip()
                            if not line:
                                break
                            key, value = line.split(': ', 1)
                            headers[key] = value
                        
                        debug(f"Cached headers: {headers}")
                        body = f.read()
                        debug(f"Cached body length: {len(body)} bytes")
                    
                    response_headers = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
                    debug("Constructing response from cache")
                    return f"{status_line}\r\nCache-Status: HIT\r\n{response_headers}\r\n\r\n".encode() + body
                except Exception as e:
                    debug(f"Error reading cache: {e}")
                    cache_file.unlink()
                    debug("Invalid cache file removed")

        debug("Cache miss - making backend request")
        try:
            status, headers, body = make_request(url, headers)
            
            if status != 200:
                debug(f"Backend returned non-200 status: {status}")
                return f"HTTP/1.1 {status} {http.client.responses.get(status, 'Unknown')}\r\n\r\n".encode()
            
            debug("Storing response in cache")
            with cache_file.open('wb') as f:
                f.write(f"HTTP/1.1 {status} OK\r\n".encode())
                for key, value in headers.items():
                    f.write(f"{key}: {value}\r\n".encode())
                f.write(b"\r\n")
                f.write(body)
            
            debug("Constructing response from backend")
            response_headers = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
            return f"HTTP/1.1 200 OK\r\nCache-Status: MISS\r\n{response_headers}\r\n\r\n".encode() + body
        except Exception as e:
            debug(f"Backend request failed: {e}")
            return b"HTTP/1.1 502 Bad Gateway\r\n\r\n502 Bad Gateway"
    except Exception as e:
        debug(f"Request processing failed: {e}")
        return b"HTTP/1.1 400 Bad Request\r\n\r\n400 Bad Request"

def start_server():
    debug(f"Initializing server on port {PORT}")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind(("", PORT))
        debug(f"Socket bound to port {PORT}")
    except Exception as e:
        debug(f"Failed to bind to port {PORT}: {e}")
        sys.exit(1)
    
    server.listen(1)
    print(f"Starting proxy on port {PORT}, backend: {BACKEND}")
    debug("Server ready and listening")

    try:
        while True:
            debug("Waiting for new connection...")
            try:
                client, addr = server.accept()
                debug(f"New connection from {addr}")
                with client:
                    request = client.recv(4096).decode().strip()
                    debug(f"Received request from {addr}")
                    
                    if request:
                        debug("Processing request...")
                        response = handle_request(request)
                        if isinstance(response, str):
                            response = response.encode()
                        
                        debug("Sending response...")
                        client.sendall(response)
                        debug("Response sent successfully")
                    else:
                        debug("Empty request received")
            except Exception as e:
                debug(f"Error handling connection: {e}")
    except KeyboardInterrupt:
        debug("Keyboard interrupt received")
        print("\nShutting down...")
    finally:
        debug("Closing server socket")
        server.close()
        debug("Server shutdown complete")

if __name__ == "__main__":
    debug("Proxy starting up")
    parse_args()
    start_server()
    debug("Proxy exited")
