"""Responsive layout contracts and explicit, reviewable screenshot baselines."""
from io import BytesIO
import json
import os
from pathlib import Path
from PIL import Image, ImageChops
from test_app import BrowserTestCase

BASELINES = Path(__file__).parent / 'screenshots'
ARTIFACTS = Path(__file__).resolve().parents[1] / 'test-results' / 'visual'
SIZES = [(320,720),(390,844),(768,1024),(1440,900)]
TABS = ['theory','learn:assoc','learn:speed','learn:metro','learn:check','digits','binary','audio']


def changed_pixel_ratio(expected, actual):
    """Ignore small color/antialias differences; count materially changed pixels."""
    if expected.size != actual.size:
        return 1.0
    diff = ImageChops.difference(expected.convert('RGB'), actual.convert('RGB'))
    red, green, blue = diff.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    changed = sum(maximum.histogram()[26:])
    return changed / (expected.width * expected.height)


class VisualTests(BrowserTestCase):
    def assert_no_overflow(self):
        dimensions=self.page.evaluate('''() => ({
          width:document.documentElement.clientWidth,
          scroll:Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)
        })''')
        self.assertLessEqual(dimensions['scroll'],dimensions['width']+1,dimensions)

    def test_sections_have_no_horizontal_scroll_at_four_sizes(self):
        for width,height in SIZES:
            self.page.set_viewport_size({'width':width,'height':height})
            for target in TABS:
                with self.subTest(size=(width,height),target=target):
                    if width<980:
                        self.page.locator('#menuToggle').click()
                    self.nav(target)
                    self.assert_no_overflow()

    def test_running_sequence_layouts_have_no_horizontal_scroll(self):
        for width,height in SIZES:
            self.page.set_viewport_size({'width':width,'height':height})
            for target,prefix in [('digits','dg'),('binary','bn')]:
                with self.subTest(size=(width,height),target=target):
                    if width<980:
                        self.page.locator('#menuToggle').click()
                    self.nav(target)
                    self.seg(prefix+'.view','sheet')
                    self.page.locator('#'+prefix+'Setup .start').click()
                    self.assert_no_overflow()
                    self.page.locator('#'+prefix+'Run .to-recall').click()
                    self.assert_no_overflow()
                    self.page.locator('#'+prefix+'Run .check').click()
                    self.assert_no_overflow()
                    self.page.locator('#'+prefix+'Run .back').click()

    def test_screenshot_baselines(self):
        update=os.environ.get('UPDATE_SCREENSHOTS')=='1'
        ARTIFACTS.mkdir(parents=True,exist_ok=True)
        if update:
            BASELINES.mkdir(parents=True,exist_ok=True)
            (BASELINES/'metadata.json').write_text(json.dumps({
                'browser':self.browser.version,'sizes':SIZES,
                'color_threshold':25,'max_changed_pixel_ratio':0.01
            },indent=2)+'\n')
        for width,height in SIZES:
            self.page.set_viewport_size({'width':width,'height':height})
            self.page.evaluate('localStorage.clear()')
            self.page.reload()
            for target in ['theory','learn:assoc','digits','binary','audio']:
                with self.subTest(size=(width,height),target=target):
                    if width<980:
                        self.page.locator('#menuToggle').click()
                    self.nav(target)
                    self.page.evaluate('''async () => {
                      await document.fonts.ready;
                      window.scrollTo(0,0); document.activeElement?.blur();
                      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
                    }''')
                    name=f'{target.replace(":","-")}-{width}x{height}.png'
                    actual_bytes=self.page.screenshot(full_page=True,animations='disabled',caret='hide')
                    actual_path=ARTIFACTS/name
                    actual_path.write_bytes(actual_bytes)
                    baseline=BASELINES/name
                    if update:
                        baseline.write_bytes(actual_bytes)
                        continue
                    self.assertTrue(baseline.exists(),f'Missing baseline: {baseline}; see tests/README.md')
                    with Image.open(baseline) as expected, Image.open(BytesIO(actual_bytes)) as actual:
                        ratio=changed_pixel_ratio(expected,actual)
                        if expected.size==actual.size and ratio>0.01:
                            ImageChops.difference(expected.convert('RGB'),actual.convert('RGB')).save(
                                ARTIFACTS/(name.removesuffix('.png')+'-diff.png'))
                        self.assertLessEqual(ratio,0.01,
                            f'{name}: {ratio:.2%} of pixels changed; actual/diff are in {ARTIFACTS}')

    def test_visual_comparison_detects_large_layout_change(self):
        self.nav('digits')
        before=Image.open(BytesIO(self.page.screenshot()))
        self.page.add_style_tag(content='.wrap { transform: translateY(100px); }')
        after=Image.open(BytesIO(self.page.screenshot()))
        self.assertGreater(changed_pixel_ratio(before,after),0.01)
