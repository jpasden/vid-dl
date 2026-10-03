import json
import importlib.util
import unittest
from unittest.mock import patch

import server


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.job = {'percent': 0}
        self.tracker = server.DownloadProgress(self.job)

    def metadata(self, formats):
        self.tracker.consume(server.META_PREFIX + json.dumps({
            'title': 'A "quoted" title 中文', 'formats': formats}))

    def progress(self, format_id, downloaded, total=None, status='downloading'):
        self.tracker.consume(server.PROGRESS_PREFIX + json.dumps({
            'format_id': format_id, 'progress': {'downloaded_bytes': downloaded,
            'total_bytes': total, 'status': status}}))
        return self.job['percent']

    def test_two_streams_make_one_bar_and_ignore_subtitles(self):
        self.metadata([{'format_id': 'video', 'filesize': 900},
                       {'format_id': 'audio', 'filesize': 100}])
        self.assertEqual(self.job['title'], 'A "quoted" title 中文')
        values = [self.progress('subtitles', 100, 100),
                  self.progress('video', 450, 900),
                  self.progress('video', 900, 900, 'finished'),
                  self.progress('audio', 1, 100),
                  self.progress('audio', 100, 100, 'finished')]
        self.assertEqual(values[0], 0)
        self.assertEqual(values, sorted(values))
        self.assertAlmostEqual(values[2], 89.1)
        self.assertEqual(values[-1], 99)
        self.assertEqual(self.job['phase'], 'finishing')

    def test_estimates_and_retries_cannot_rewind(self):
        formats = [{'format_id': 'video', 'filesize_approx': 100}]
        self.metadata(formats)
        first = self.progress('video', 80, 100)
        self.assertEqual(self.progress('video', 81, 200), first)
        self.tracker = server.DownloadProgress(self.job)
        self.metadata(formats)
        self.assertEqual(self.progress('video', 1, 100), first)

    def test_unknown_sizes_reserve_room_for_second_stream(self):
        self.metadata([{'format_id': 'video'}, {'format_id': 'audio'}])
        self.assertEqual(self.progress('video', 100, status='finished'), 49.5)
        self.assertEqual(self.progress('audio', 100, status='finished'), 99)

    def test_single_stream_and_malformed_events(self):
        self.tracker.consume(server.META_PREFIX + json.dumps({
            'title': 'Single stream', 'format_id': 'one', 'formats': 'NA'}))
        self.assertEqual(self.progress('one', 50, 100), 49.5)
        self.assertTrue(self.tracker.consume(server.PROGRESS_PREFIX + 'invalid'))
        self.assertEqual(self.job['percent'], 49.5)

    @unittest.skipUnless(importlib.util.find_spec('yt_dlp'), 'yt-dlp not installed')
    def test_real_templates_produce_json_with_missing_sizes(self):
        import yt_dlp
        with patch.object(server, 'have_cookie_file', return_value=False):
            cmd = server.build_command('test-url', 'video')
        template = cmd[cmd.index('--print') + 1].removeprefix('before_dl:')
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            for formats in (None, [{'format_id': 'video'}, {'format_id': 'audio'}]):
                info = {'title': 'Quotes " & 中文', 'format_id': 'video'}
                if formats:
                    info['requested_formats'] = formats
                line = ydl.evaluate_outtmpl(template, info)
                parsed = json.loads(line[len(server.META_PREFIX):])
                self.assertEqual(parsed['filesize'], 0)
                self.tracker.consume(line)
                self.assertEqual(self.job['title'], info['title'])

    def test_only_success_records_completion_time_and_100_percent(self):
        for rc, expected_status in [(0, 'done'), (1, 'error')]:
            with self.subTest(rc=rc):
                job = {'percent': 99, 'log': [], 'completed_at': None}
                with patch.dict(server.JOBS, {'test': job}), \
                     patch.object(server, 'build_command', return_value=[]), \
                     patch.object(server, 'run_ytdlp', return_value=rc):
                    server.run_job('test', 'test-url', 'video')
                self.assertEqual(job['status'], expected_status)
                self.assertEqual(job['percent'], 100 if rc == 0 else 99)
                self.assertEqual(job['completed_at'] is not None, rc == 0)


if __name__ == '__main__':
    unittest.main()
