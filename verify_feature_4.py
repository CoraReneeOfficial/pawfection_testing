import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("Navigating to store login...")
        await page.goto('http://127.0.0.1:5000/login')

        print("Logging in to store...")
        await page.fill('input[name="username"]', 'teststore')
        await page.fill('input[name="password"]', 'password123')
        await page.click('button[type="submit"]')

        await asyncio.sleep(1) # wait for redirect to user login

        print("Logging in as groomer user...")
        await page.fill('input[name="username"]', 'groomer')
        await page.fill('input[name="password"]', 'password123')
        await page.click('button[type="submit"]')

        print("Waiting for dashboard...")
        await asyncio.sleep(2) # Give it some time to load

        print("Taking screenshot of dashboard...")
        await page.screenshot(path='/home/jules/verification/dashboard_groomer.png', full_page=True)

        # Test clicking a toggle
        print("Trying to click a toggle btn...")
        try:
            await page.click('.toggle-btn.check-in')
            await asyncio.sleep(1) # Wait for fetch call and UI update
            await page.screenshot(path='/home/jules/verification/dashboard_toggled.png', full_page=True)
            print("Successfully clicked toggle!")
        except Exception as e:
            print("Failed to click toggle btn:", e)

        await browser.close()

asyncio.run(run())
