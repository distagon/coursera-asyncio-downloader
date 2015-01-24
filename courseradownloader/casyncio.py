import time
import os
import sys
import argparse
import asyncio
import posixpath
import logging
import urllib.parse
from aiohttp import request, EofStream
from colorama import init as colorama_init, Fore
from pyquery import PyQuery as pq
from collections import namedtuple


logging.basicConfig()
logger = logging.getLogger('coursera')
logger.setLevel(logging.INFO)


ProcessMessage = namedtuple('ProcessMessage', 'size')
SkippedMessage = namedtuple('SkippedMessage', 'filename')
FinishedMessage = namedtuple('FinishedMessage', 'filename size')
DoneMessage = namedtuple('DoneMessage', 'size')
WheelMessage = namedtuple('WheelMessage', 'shape')
InitialMessage = namedtuple('InitialMessage', 'number')
FILE_SIZES = ('', 'KB', 'MB', 'GB')


def _print_color_line(text, color, same_line=False, last_string_length=[0]):
    message = '{}{}{}'.format(color, text, Fore.RESET)
    if not same_line:
        print(message)
        return
    message_length = len(message)
    spaces = 0
    if last_string_length[0] > message_length:
        spaces = last_string_length[0] - message_length
    last_string_length[0] = message_length + spaces
    message = '{}{}{}'.format(
        message, ' ' * spaces, '\b' * (len(text) + spaces))
    sys.stdout.write(message)
    sys.stdout.flush()


def request_to_str(request):
    return('<ClientResponse({}{}) [{} {}]>'.format(
        request.host, request.url, request.status, request.reason))


def format_size(size):
    index = 0
    while size > 1024 and index < len(FILE_SIZES) - 1:
        size /= 1024.0
        index += 1
    return size, FILE_SIZES[index]


@asyncio.coroutine
def _http_request(url, method='GET', headers=None, cookies=None, **kwargs):
    result = yield from request(
        method, url, headers=headers, cookies=cookies, **kwargs)
    return result


def send_message(coroutine, klass, *messages):
    if coroutine is not None:
        try:
            coroutine.send(klass(*messages))
        except StopIteration:
            pass


def prepare_downloader_info():

    @asyncio.coroutine
    def downloader_info():
        current_size = 0
        wheel_pos_changed = False
        wheel_current_pos = '-'
        number_of_finished_files = 0
        message_str = '[{0}][{1}/{2}][{3:0.2f}{4}/s]'
        done = False
        while True:
            initial_message = (yield)
            if isinstance(initial_message, InitialMessage):
                number_of_files = initial_message.number
                break
        start_time = time.time()
        while not done:
            message = (yield)
            if isinstance(message, ProcessMessage):
                current_size += message.size
            elif isinstance(message, WheelMessage):
                wheel_current_pos = message.shape
                wheel_pos_changed = True
            elif isinstance(message, FinishedMessage):
                number_of_finished_files += 1
                size, quantify = format_size(message.size)
                message_text = 'Finished: {}. Size {:0.2f}{}'.format(
                    message.filename, size, quantify)
                _print_color_line(message_text, Fore.GREEN)
            elif isinstance(message, SkippedMessage):
                number_of_finished_files += 1
                _print_color_line(
                    'Skipped: {}'.format(message.filename), Fore.RED)
            elif isinstance(message, DoneMessage):
                current_size += message.size
                done = True
            elapsed_time = time.time() - start_time
            if wheel_pos_changed or elapsed_time >= 2 or done:
                speed, quantify = format_size(
                    current_size / float(elapsed_time))
                message_text = message_str.format(
                    wheel_current_pos, number_of_finished_files,
                    number_of_files, speed, quantify)
                _print_color_line(message_text, Fore.RED, same_line=True)
                if elapsed_time >= 2:
                    start_time = time.time()
                    current_size = 0
                if wheel_pos_changed:
                    wheel_pos_changed = False

    info_coroutine = downloader_info()
    next(info_coroutine)
    return info_coroutine


class CourseraParser:

    ROOT_ELEMENT = ".course-item-list-section-list"
    HEADER_SUBLEMENT = "h3"
    CHAPTER_ELEMENT = ".course-lecture-item-resource"

    def __init__(self, page):
        self.page = page

    def parse_page(self):
        _print_color_line("Getting files list...", Fore.RED)
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

    def __init__(self, directory, url, info_coroutine,
                 sem, headers=None, cookies=None):
        self.directory = directory
        self.url = url
        self.cookies = cookies
        self.headers = headers
        self.fl = None
        self.sem = sem
        self.info_coroutine = info_coroutine

    @staticmethod
    def check_filename(filename, content_length=None):
        if not os.path.exists(filename):
            return True
        if content_length is None:
            return False
        if not content_length.isdigit():
            return True
        return os.path.getsize(filename) != int(content_length)

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
            if self.url.endswith('/'):
                # non file
                return
            path = urllib.parse.urlsplit(self.url)
            filename = posixpath.basename(path)
        return filename, content_length

    @asyncio.coroutine
    def start(self):
        with (yield from self.sem):
            result = yield from self._get_file_name()
            if result is None or result[0] is None:
                logger.error(
                    "Cannot get filename from url {}. Skipped".
                    format(self.url))
                return
            filename, content_length = result
            filename_path = os.path.normpath(os.path.abspath(
                os.path.join(self.directory, filename)))
            if not self.check_filename(filename_path, content_length):
                send_message(self.info_coroutine, SkippedMessage, filename)
                return
            self.filename = filename
            try:
                self.fl = yield from self._open_file(filename_path)
            except OSError as err:
                logger.error(
                    "Cannot open file: {0}. {1}".format(filename_path, err))
                return
            bytes = yield from self._download_file()
            if bytes:
                send_message(
                    self.info_coroutine, FinishedMessage, filename, bytes)

    @asyncio.coroutine
    def _download_file(self):
        size = 0
        response = None
        buf = 2048
        try:
            response = yield from _http_request(
                self.url, method='GET', headers=self.headers,
                cookies=self.cookies)
            if response.status >= 400:
                logger.error(request_to_str(response))
                return
            current_size = 0
            try:
                while True:
                    chunk = yield from response.content.read(buf)
                    if not chunk:
                        break
                    current_size = yield from self._write_to_file(chunk)
                    send_message(
                        self.info_coroutine, ProcessMessage, current_size)
                    size += current_size
                send_message(self.info_coroutine, ProcessMessage, current_size)
                return size
            except EofStream:
                send_message(self.info_coroutine, ProcessMessage, current_size)
                return size
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.exception(e)
        finally:
            if response is not None:
                response.close()
            self.fl.close()

    @asyncio.coroutine
    def _write_to_file(self, chunk):
        return self.fl.write(chunk)

    @asyncio.coroutine
    def _open_file(self, filename):
        return open(filename, 'wb')


class Downloader:

    AUTH_COOKIE_NAME = "CAUTH"
    CSRF_TOKEN_COOKIE_NAME = "csrf_token"
    PASSWORD_FIELD_NAME = "password"
    USERNAME_FIELD_NAME = "email"
    LECTURE_CSRF_URL = "https://class.coursera.org/{}"
    LECTURE_URL = "https://class.coursera.org/{}/lecture"
    LOGIN_URL = "https://accounts.coursera.org/api/v1/login"
    REFERRER_URL = "https://accounts.coursera.org/signin"
    CLASS_AUTH_URL = (
        "https://class.coursera.org/{}/auth/auth_redirector?"
        "type=login&subtype=normal")
    REQUESTS_HEADERS = {"Accept": "*/*", "User-Agent": "coursera-client"}

    def __init__(self, classname, username,
                 password, concurrency, directory, chapter=None):
        self.class_name = classname
        self.username = username
        self.password = password
        self.chapter = chapter
        self.concurrency = concurrency
        self.directory = directory
        self.auth_cookies = None
        self.info_coroutine = prepare_downloader_info()

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
        data = {
            self.USERNAME_FIELD_NAME: self.username,
            self.PASSWORD_FIELD_NAME: self.password,
            'webrequest': 'true'
        }
        response = yield from _http_request(
            self.LOGIN_URL, method="POST", headers=headers,
            cookies=cookies, data=data)
        auth_cookies = response.cookies.get(self.AUTH_COOKIE_NAME)
        if auth_cookies is not None:
            self.auth_cookies = auth_cookies.value

    @asyncio.coroutine
    def _get_session_cookies(self):
        _print_color_line("Authenticating...", Fore.RED)
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
            logger.info("There is nothing to download")
            return
        colorama_init()
        number_of_files = sum([len(res[1]) for res in result])
        _print_color_line(
            "Starting to download {} files".
            format(number_of_files), Fore.GREEN)
        sem = asyncio.Semaphore(self.concurrency)
        downloaders = []
        cookies = {self.AUTH_COOKIE_NAME: self.auth_cookies}
        send_message(self.info_coroutine, InitialMessage, number_of_files)
        for name, links in result:
            directory = os.path.join(self.directory, name)
            if not os.path.exists(directory):
                os.mkdir(directory)
            for link in links:
                downloader = FileDownloader(
                    directory, link, self.info_coroutine,
                    headers=self.REQUESTS_HEADERS, cookies=cookies, sem=sem)
                downloaders.append(downloader.start())
        return (yield from asyncio.wait(downloaders))

    @asyncio.coroutine
    def wheel(self, delay):
        wheel_pos = ('-', '\\', '|', '/')
        counter = 0
        while True:
            yield from asyncio.sleep(delay)
            pos = wheel_pos[counter % len(wheel_pos)]
            send_message(self.info_coroutine, WheelMessage, pos)
            next_counter = counter + 1
            counter = (0 if next_counter % len(wheel_pos) == 0
                       else next_counter)

    def start(self):
        wheel_task = asyncio.Task(self.wheel(0.5))
        loop = asyncio.get_event_loop()
        future = self.prepare()
        try:
            loop.run_until_complete(future)
        except KeyboardInterrupt:
            pass
        try:
            wheel_task.cancel()
            send_message(self.info_coroutine, DoneMessage, 0)
        except StopIteration:
            pass
        loop.close()
