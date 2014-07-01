import os
import argparse
import asyncio
import logging
import urllib.parse
from aiohttp import request, EofStream
from colorama import init as colorama_init, Fore
from pyquery import PyQuery as pq


logging.basicConfig()
logger = logging.getLogger('coursera')
logger.setLevel(logging.INFO)


def _print_color(text, color):
    print("{}{}{}".format(color, text, Fore.RESET))


def request_to_str(request):
    return('<ClientResponse({}{}) [{} {}]>'.format(
        request.host, request.url, request.status, request.reason))


@asyncio.coroutine
def _http_request(url, method="GET", headers=None, cookies=None, **kwargs):
    return (yield from request(
        method, url, headers=headers, cookies=cookies, **kwargs))


class CourseraParser:

    ROOT_ELEMENT = ".course-item-list-section-list"
    HEADER_SUBLEMENT = "h3"
    CHAPTER_ELEMENT = ".course-lecture-item-resource"

    def __init__(self, page):
        self.page = page

    def parse_page(self):
        logger.info("Getting files list...")
        root_elements = pq(self.page)(self.ROOT_ELEMENT)
        return [self._parse_element(el) for el in root_elements]

    def _parse_element(self, el):
        header = pq(pq(el).prevAll()[-1]).find(self.HEADER_SUBLEMENT).\
            text().strip().replace("\u00a0", "")
        return header, [
            CourseraParser._decode_url(link.attrib['href'])
            for chapter in pq(el).find(self.CHAPTER_ELEMENT)
            for link in pq(chapter).find("a")]

    @staticmethod
    def _decode_url(url):
        return urllib.parse.unquote(url)


class FileDownloader:

    def __init__(self, directory, url, sem, headers=None, cookies=None):
        self.directory = directory
        self.url = url
        self.cookies = cookies
        self.headers = headers
        self.fl = None
        self.sem = sem

    @staticmethod
    def check_filename(filename, content_length=None):
        return (
            not os.path.exists(filename) or
            content_length is None or not content_length.isdigit() or
            os.path.getsize(filename) != int(content_length))

    @asyncio.coroutine
    def _get_file_data(self):
        response = None
        try:
            response = yield from _http_request(
                self.url, method='GET', headers=self.headers,
                cookies=self.cookies, allow_redirects=False)
            if response.status >= 400:
                logger.error(request_to_str(response))
                return response.headers
            return response.headers
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.exception(e)
        finally:
            if response is not None:
                response.close()

    @asyncio.coroutine
    def _get_file_name(self):
        headers = yield from self._get_file_data()
        if headers is None:
            return
        location = headers.get("Location")
        if location is not None:
            self.url = location
            return (yield from self._get_file_name())
        content_length = headers.get("Content-Length")
        content_disposition = headers.get("Content-Disposition")
        if content_disposition is not None:
            filename = urllib.parse.unquote(
                content_disposition.split(";")[1].strip().
                split("=")[-1]).strip("\"\'")
        else:
            filename = None
        return filename, content_length

    @asyncio.coroutine
    def start(self):
        with (yield from self.sem):
            result = yield from self._get_file_name()
            if result is None or result[0] is None:
                logger.error(
                    "Cannot get filename from url {}. Passed".format(self.url))
                return 0
            filename, content_length = result
            filename_path = os.path.normpath(os.path.abspath(
                os.path.join(self.directory, filename)))
            if not self.check_filename(filename_path, content_length):
                _print_color("Skipped: {}".format(filename), Fore.RED)
                return 0
            self.fl = self._open_file(filename_path)
            bytes = yield from self._download_file()
            if bytes:
                _print_color(
                    "Finished: {}. Size {} bytes".format(filename, bytes),
                    Fore.GREEN)

    @asyncio.coroutine
    def _download_file(self):
        size = 0
        response = None
        try:
            response = yield from _http_request(
                self.url, method='GET', headers=self.headers,
                cookies=self.cookies)
            if response.status >= 400:
                logger.error(request_to_str(response))
                return
            try:
                while True:
                    chunk = yield from response.content.read()
                    if chunk.strip() == b'':
                        continue
                    size += yield from self._write_to_file(chunk)
                return size
            except EofStream:
                return size
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.exception(e)
        finally:
            if response is not None:
                response.close()
            self.fl.close()

    def _open_file(self, filename):
        return open(filename, 'wb')

    @asyncio.coroutine
    def _write_to_file(self, chunk):
        return self.fl.write(chunk)


class Downloader:

    AUTH_COOKIE_NAME = "CAUTH"
    CSRF_TOKEN_COOKIE_NAME = "csrf_token"
    PASSWORD_FIELD_NAME = "password"
    USERNAME_FIELD_NAME = "email"
    LECTURE_URL = "https://class.coursera.org/{}/lecture/index"
    LECTURE_CSRF_URL = "https://class.coursera.org/{}/lecture"
    LOGIN_URL = "https://accounts.coursera.org/api/v1/login"
    REFERRER_URL = "https://accounts.coursera.org/signin"
    CLASS_AUTH_URL = (
        "https://class.coursera.org/{}/auth/auth_redirector?"
        "type=login&subtype=normal")
    REQUESTS_HEADERS = {"Accept": "*/*", "User-Agent": "coursera-client"}

    def __init__(self, class_name, username,
                 password, concurrency, directory, chapter=None):
        self.class_name = class_name
        self.username = username
        self.password = password
        self.chapter = chapter
        self.concurrency = concurrency
        self.directory = directory
        self.auth_cookies = None

    @asyncio.coroutine
    def _get_csrf_token(self):
        url = self.LECTURE_CSRF_URL.format(self.class_name)
        response = yield from _http_request(
            url, method="GET", headers=self.REQUESTS_HEADERS,
            allow_redirects=False)
        cookies = response.cookies
        return cookies.get(self.CSRF_TOKEN_COOKIE_NAME).value

    @asyncio.coroutine
    def _get_auth_cookies(self):
        csrf_token = yield from self._get_csrf_token()
        headers = {
            "Referer": self.REFERRER_URL,
            "X-CSRFToken": csrf_token
        }
        headers.update(self.REQUESTS_HEADERS)
        cookies = {"csrftoken": csrf_token}
        data = {self.USERNAME_FIELD_NAME: self.username,
                self.PASSWORD_FIELD_NAME: self.password}
        response = yield from _http_request(
            self.LOGIN_URL, method="POST", headers=headers,
            cookies=cookies, data=data)
        auth_cookies = response.cookies.get(self.AUTH_COOKIE_NAME)
        if auth_cookies is not None:
            self.auth_cookies = auth_cookies.value

    @asyncio.coroutine
    def _get_session_cookies(self):
        logger.info("Authenticating...")
        yield from self._get_auth_cookies()
        if self.auth_cookies is None:
            return
        cookies = {self.AUTH_COOKIE_NAME: self.auth_cookies}
        url = self.CLASS_AUTH_URL.format(self.class_name)
        response = yield from _http_request(
            url, method="GET", headers=self.REQUESTS_HEADERS, cookies=cookies)

    @asyncio.coroutine
    def _get_class_page(self):
        cookies = {self.AUTH_COOKIE_NAME: self.auth_cookies}
        response = yield from _http_request(
            self.LECTURE_URL.format(self.class_name),
            method="GET", headers=self.REQUESTS_HEADERS, cookies=cookies)
        return (yield from response.content.read())

    @asyncio.coroutine
    def _get_class_links(self):
        yield from self._get_session_cookies()
        if self.auth_cookies is None:
            return
        cookies = {self.AUTH_COOKIE_NAME: self.auth_cookies}
        page = yield from self._get_class_page()
        return CourseraParser(page).parse_page()

    @asyncio.coroutine
    def prepare(self):
        result = yield from self._get_class_links()
        if result is None:
            logger.error(
                "Cannot get list of links to download. "
                "Check username and password")
            return
        if self.chapter is not None:
            result = result[self.chapter - 1:]
        if not result:
            logger.info("Nothing to download")
            return
        colorama_init()
        number_of_files = sum([len(res[1]) for res in result])
        _print_color(
            "Starting to download {} files".format(number_of_files), Fore.RED)
        sem = asyncio.Semaphore(self.concurrency)
        downloaders = []
        cookies = {self.AUTH_COOKIE_NAME: self.auth_cookies}
        for name, links in result:
            directory = os.path.join(self.directory, name)
            if not os.path.exists(directory):
                os.mkdir(directory)
            for link in links:
                downloader = FileDownloader(
                    directory, link, headers=self.REQUESTS_HEADERS,
                    cookies=cookies, sem=sem)
                downloaders.append(downloader.start())
        return (yield from asyncio.wait(downloaders))

    def start(self):
        loop = asyncio.get_event_loop()
        future = self.prepare()
        try:
            loop.run_until_complete(future)
        except KeyboardInterrupt:
            pass
        loop.close()
