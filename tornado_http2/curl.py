import pycurl
from tornado import curl_httpclient

try:
    CURL_HTTP_VERSION_2 = pycurl.CURL_HTTP_VERSION_2
except AttributeError:
    # Pycurl doesn't yet have this constant even when libcurl does.
    CURL_HTTP_VERSION_2 = pycurl.CURL_HTTP_VERSION_1_1 + 1


class CurlAsyncHTTP2Client(curl_httpclient.CurlAsyncHTTPClient):
    def _curl_setup_request(self, curl, request, buffer, headers):
        super(CurlAsyncHTTP2Client, self)._curl_setup_request(
            curl, request, buffer, headers)

        curl.setopt(pycurl.HTTP_VERSION, CURL_HTTP_VERSION_2)

    def _finish(self, curl, curl_error=None, curl_message=None):
        # Work around a bug in curl 7.41: if the connection is closed
        # during an Upgrade request, this is not reported as an error
        # but status is zero.
        if not curl_error:
            code = curl.getinfo(pycurl.HTTP_CODE)
            if code == 0:
                curl_error = pycurl.E_PARTIAL_FILE
        super(CurlAsyncHTTP2Client, self)._finish(
            curl, curl_error=curl_error, curl_message=curl_message)
