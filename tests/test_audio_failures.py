"""Audio fault injection with real codecs, audio graph and recording pipeline."""
from playwright.sync_api import expect
from test_app import BrowserTestCase


class AudioFailureTests(BrowserTestCase):
    def probe_sources(self):
        self.page.evaluate('''() => {
          window.playbacks=[];
          const start=AudioBufferSourceNode.prototype.start;
          AudioBufferSourceNode.prototype.start=function(...args) {
            const entry={duration:this.buffer.duration,time:args[0],ended:false};
            this.addEventListener('ended',()=>entry.ended=true);
            playbacks.push(entry); return start.apply(this,args);
          };
        }''')

    def test_sound_check_resumes_suspended_context_and_replays(self):
        self.nav('audio')
        self.probe_sources()
        self.page.evaluate('async () => { await getCtx().resume(); await getCtx().suspend(); }')
        self.assertEqual(self.page.evaluate('getCtx().state'), 'suspended')
        self.page.locator('#auTest').click()
        self.page.wait_for_function('playbacks.length === 3')
        self.assertEqual(self.page.evaluate('getCtx().state'), 'running')
        self.page.wait_for_function('playbacks.every(p=>p.ended)', timeout=6000)
        self.page.evaluate('async () => { await getCtx().suspend(); }')
        self.page.locator('#auTest').click()
        self.page.wait_for_function('playbacks.length === 6')
        self.page.wait_for_function('playbacks.every(p=>p.ended)', timeout=6000)
        self.assertEqual(self.page.evaluate('getCtx().state'), 'running')

    def test_training_pause_freezes_audio_time_and_resume_finishes_playback(self):
        self.nav('audio')
        self.count('au.count', 2)
        self.page.locator('#auInterval').select_option('0.5')
        self.probe_sources()
        self.page.locator('#auSetup .start').click()
        self.page.locator('#auRun .pause').click()
        self.page.wait_for_function('getCtx().state === "suspended"')
        paused_at = self.page.evaluate('getCtx().currentTime')
        # Use elapsed real time: advancing JS timers alone cannot prove audio paused.
        self.page.wait_for_timeout(300)
        self.assertAlmostEqual(self.page.evaluate('getCtx().currentTime'), paused_at, places=4)
        self.assertEqual(self.page.evaluate('playbacks.filter(p=>p.ended).length'), 0)
        self.page.locator('#auRun .pause').click()
        self.page.wait_for_function('getCtx().state === "running"')
        self.page.wait_for_function('playbacks.every(p=>p.ended)', timeout=8000)
        expect(self.page.locator('#auRun input')).to_have_count(1, timeout=8000)
        self.page.locator('#auRun .cancel').click()
        self.page.locator('#auTest').click()
        self.page.wait_for_function('playbacks.length === 5')
        self.page.wait_for_function('playbacks.every(p=>p.ended)', timeout=6000)

    def test_corrupt_embedded_mp3_reports_error_and_retry_succeeds(self):
        self.nav('audio')
        self.count('au.count', 2)
        self.page.evaluate('''() => {
          window.savedMp3=EN_VOICE_MP3[4]; EN_VOICE_MP3[4]=btoa('invalid MP3 bytes');
        }''')
        self.page.locator('#auSetup .start').click()
        expect(self.page.locator('#auVoiceInfo')).to_contain_text('Не получилось подготовить звук')
        expect(self.page.locator('#auSetup .start')).to_be_enabled()
        expect(self.page.locator('#auRun')).to_be_hidden()
        self.assertTrue(self.page.evaluate('enBufs === null'))
        self.page.evaluate('() => { EN_VOICE_MP3[4]=savedMp3; }')
        self.page.locator('#auSetup .start').click()
        expect(self.page.locator('#auRun .stop')).to_be_visible()
        self.page.locator('#auRun .stop').click()

    def microphone_stream(self, volume):
        self.page.evaluate('''volume => {
          navigator.mediaDevices.getUserMedia=async () => {
            const ctx=getCtx(); await ctx.resume();
            const dest=ctx.createMediaStreamDestination();
            const oscillator=ctx.createOscillator(), gain=ctx.createGain();
            gain.gain.value=volume;
            oscillator.connect(gain); gain.connect(dest); oscillator.start();
            window.testMicrophone={oscillator,dest}; return dest.stream;
          };
        }''', volume)
        self.page.locator('#auRecorder summary').click()

    def test_quiet_microphone_is_rejected_and_not_saved(self):
        self.nav('audio')
        self.microphone_stream(0.001)
        self.page.locator('#voiceGrid .voice-tile').first.locator('.rec').click()
        expect(self.page.locator('#voiceMsg')).to_contain_text('слишком тихо', timeout=8000)
        expect(self.page.locator('#voiceGrid .has')).to_have_count(0)
        self.assertEqual(self.page.evaluate('async () => Object.keys(await VoiceDB.all())'), [])
        self.assertFalse(self.page.evaluate('recording'))
        self.page.evaluate('testMicrophone.oscillator.stop()')
        self.page.reload()
        expect(self.page.locator('#voiceGrid .has')).to_have_count(0)

    def test_corrupt_microphone_recording_reports_error_and_allows_rerecording(self):
        self.nav('audio')
        self.microphone_stream(0.3)
        # Preserve the real recorder; replace only its emitted data with corrupt bytes.
        self.page.evaluate('''() => {
          const Recorder=MediaRecorder;
          window.originalRecorder=Recorder;
          window.MediaRecorder=class extends Recorder {
            set ondataavailable(handler) {
              super.ondataavailable=() => handler({data:new Blob(['broken audio'])});
            }
          };
        }''')
        self.page.locator('#voiceGrid .voice-tile').first.locator('.rec').click()
        expect(self.page.locator('#voiceMsg')).to_contain_text('Не получилось обработать запись', timeout=8000)
        expect(self.page.locator('#voiceGrid .has')).to_have_count(0)
        self.assertFalse(self.page.evaluate('recording'))
        self.page.evaluate('() => { window.MediaRecorder=originalRecorder; }')
        self.page.locator('#voiceGrid .voice-tile').first.locator('.rec').click()
        expect(self.page.locator('#voiceGrid .has')).to_have_count(1, timeout=8000)
        self.page.evaluate('testMicrophone.oscillator.stop()')

    def test_corrupt_saved_own_voice_does_not_raise_unhandled_error(self):
        self.nav('audio')
        self.page.evaluate('''async () => {
          for(let d=0;d<10;d++) await VoiceDB.put(String(d),{
            sr:22050, pcm:d===3 ? [] : Float32Array.from({length:2205},()=>.2)
          });
        }''')
        self.page.reload()
        self.seg('au.voice', 'own')
        self.page.locator('#auSetup .start').click()
        expect(self.page.locator('#auVoiceInfo')).to_contain_text('Не получилось подготовить звук')
        expect(self.page.locator('#auSetup .start')).to_be_enabled()
        expect(self.page.locator('#auRun')).to_be_hidden()
