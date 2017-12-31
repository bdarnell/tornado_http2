tornado_http2
=============

This package contains an HTTP/2 client and server implementation for
[Tornado](http://www.tornadoweb.org). It is currently under
development and interfaces are subject to change.

Installation
------------

    pip install git+https://github.com/bdarnell/tornado_http2.git

This package has only been tested with Tornado 4.5 on Python 2.7.10+ and 3.5.

Server-side usage
-----------------

Two server classes are provided:
* `tornado_http2.server.Server` only supports HTTP/2 over HTTPS
connections and will use HTTP/1 for all unencrypted connections.
* `tornado_http2.server.CleartextHTTP2Server` supports HTTP/2 for
both HTTP and HTTPS connections. Note that most browsers will only use
HTTP/2 over HTTPS, and `CleartextHTTP2Server` is a little slower than
a regular `Server`, so it is mainly provided for testing purposes.

Both server classes can be used in two different ways: either instantiate them directly in place of a `tornado.httpserver.HTTPServer`:

    server = tornado_http2.server.Server(app, ssl_options=...)
    server.listen(...)

Or use `HTTPServer.configure` to change all `HTTPServers` in the process, including those created by methods like `Application.listen` or `AsyncHTTPTestCase`:

    tornado.httpserver.HTTPServer.configure('tornado_http2.server.Server')
    app.listen(...)

Client-side usage
-----------------

Three client classes are provided:
* `tornado_http2.client.Client` only supports HTTP/2 over HTTPS and
will use HTTP/1 for all unencrypted connections.
* `tornado_http2.client.ForceHTTP2Client` *only* supports HTTP/2 and
will use it for both HTTP and HTTPS. Since it cannot talk to HTTP/1
servers, it is mainly for testing purposes.
* `tornado_http2.curl.CurlAsyncHTTP2Client` requires a version of
libcurl that is compiled with HTTP/2 support, and supports HTTP/2 over
both HTTP and HTTPS, falling back to HTTP/1 when HTTP/2 is
unsupported.

Both client classes can be used in two different ways: either instantiate them directly in place of a `tornado.httpclient.AsyncHTTPClient` (be careful with `AsyncHTTPClient`'s instance-sharing magic):

    client = tornado_http2.client.Client(force_instance=True)

Or use `AsyncHTTPClient.configure` to change all `AsyncHTTPClients` in the process:

    tornado.httpclient.AsyncHTTPClient.configure('tornado_http2.client.Client')
