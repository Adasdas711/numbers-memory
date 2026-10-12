"""Keyboard and accessible-name contracts without pointer interactions."""
import re
from playwright.sync_api import expect
from test_app import BrowserTestCase


class AccessibilityTests(BrowserTestCase):
    def tab_to(self, selector, maximum=150):
        for _ in range(maximum):
            if self.page.evaluate('selector => document.activeElement.matches(selector)', selector):
                return
            self.page.keyboard.press('Tab')
        self.fail(f'Keyboard Tab navigation did not reach {selector}')

    def test_keyboard_only_decimal_training(self):
        self.tab_to('[data-go="digits"]')
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#tab-digits')).to_be_visible()
        self.tab_to('#dgSetup .start')
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#dgRun .memo-area')).to_be_visible()
        before = self.page.locator('#dgRun .progress-text').inner_text()
        self.page.keyboard.press('ArrowRight')
        self.assertNotEqual(self.page.locator('#dgRun .progress-text').inner_text(), before)
        self.tab_to('#dgRun .to-recall')
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#dgRun input').first).to_be_focused()
        self.page.keyboard.type('12')
        expect(self.page.locator('#dgRun input').nth(1)).to_be_focused()
        self.tab_to('#dgRun .check')
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#dgRun .stats-box')).to_be_visible()
        self.tab_to('#dgRun .back')
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#dgSetup')).to_be_visible()

    def test_mobile_menu_keyboard_trap_escape_and_focus_return(self):
        self.page.set_viewport_size({'width':390,'height':844})
        self.tab_to('#menuToggle')
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#sidebar .nav-item.active')).to_be_focused()
        self.page.keyboard.press('Shift+Tab')
        expect(self.page.locator('#menuCollapse')).to_be_focused()
        self.page.keyboard.press('Shift+Tab')
        expect(self.page.locator('#sidebar button').last).to_be_focused()
        self.page.keyboard.press('Tab')
        expect(self.page.locator('#menuCollapse')).to_be_focused()
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#menuToggle')).to_be_focused()
        expect(self.page.locator('#menuToggle')).to_have_attribute('aria-expanded','false')

    def test_keyboard_focus_has_visible_outline(self):
        for target in ['#menuCollapse','[data-go="digits"]','#dgSetup .start',
                       'input[data-store="dg.len.custom"]']:
            with self.subTest(target=target):
                self.tab_to(target)
                details=self.page.evaluate('''() => {
                  const e=document.activeElement,s=getComputedStyle(e),r=e.getBoundingClientRect();
                  return {visible:e.matches(':focus-visible'),style:s.outlineStyle,
                    width:parseFloat(s.outlineWidth),color:s.outlineColor,
                    inViewport:r.right>0 && r.left<innerWidth && r.bottom>0 && r.top<innerHeight};
                }''')
                self.assertTrue(details['visible'])
                self.assertTrue(details['inViewport'])
                self.assertNotIn(details['style'], ['none','hidden'])
                self.assertGreaterEqual(details['width'], 2)
                self.assertNotIn(details['color'], ['transparent','rgba(0, 0, 0, 0)'])
                if target=='[data-go="digits"]':
                    self.page.keyboard.press('Enter')

    def test_theory_cells_are_keyboard_reachable_and_activatable(self):
        cell=self.page.locator('.cell[data-id="25"]')
        self.assertTrue(cell.evaluate('''e => e.matches('button,a[href]') ||
          (e.hasAttribute('tabindex') && e.tabIndex>=0)'''),
          'Clickable theory cells must also be keyboard reachable')
        self.tab_to('.cell[data-id="25"]')
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#cellDetail .big')).to_contain_text('25')
        self.page.keyboard.press('Tab')
        expect(self.page.locator('.cell[data-id="26"]')).to_be_focused()
        self.page.keyboard.press('Space')
        expect(self.page.locator('#cellDetail .big')).to_contain_text('26')

    def test_focused_sequence_buttons_activate_with_space(self):
        self.nav('digits')
        self.page.locator('#dgSetup .start').click()
        self.page.locator('#dgRun .to-recall').focus()
        self.page.keyboard.press('Space')
        expect(self.page.locator('#dgRun input').first).to_be_focused()
        self.page.locator('#dgRun .check').focus()
        self.page.keyboard.press('Space')
        expect(self.page.locator('#dgRun .stats-box')).to_be_visible()
        self.page.locator('#dgRun .back').focus()
        self.page.keyboard.press('Enter')
        expect(self.page.locator('#dgSetup')).to_be_visible()

    def test_visible_buttons_have_accessible_names(self):
        for target in ['theory','learn:assoc','learn:speed','learn:metro','learn:check',
                       'digits','binary','audio']:
            with self.subTest(target=target):
                self.nav(target)
                for button in self.page.get_by_role('button').all():
                    if button.is_visible():
                        # ARIA snapshot uses Chromium's accessible name, not innerText.
                        snapshot=button.aria_snapshot()
                        self.assertRegex(snapshot,r'^- button "[^\"]+"',snapshot)

    def test_recording_buttons_identify_action_and_digit(self):
        self.nav('audio')
        self.page.locator('#auRecorder summary').click()
        for digit in range(10):
            with self.subTest(digit=digit):
                tile=self.page.locator(f'.voice-tile[data-d="{digit}"]')
                record=tile.get_by_role('button',name=re.compile(f'Записать.*{digit}')).count()
                play=tile.get_by_role('button',name=re.compile(f'(Воспроизвести|Прослушать).*{digit}')).count()
                self.assertEqual((record,play),(1,1),
                    f'Both buttons must identify their action and digit {digit}')
