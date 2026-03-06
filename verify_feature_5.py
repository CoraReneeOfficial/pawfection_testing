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

        await asyncio.sleep(1)

        print("Logging in as groomer user...")
        await page.fill('input[name="username"]', 'groomer')
        await page.fill('input[name="password"]', 'password123')
        await page.click('button[type="submit"]')

        await asyncio.sleep(2)

        print("Navigating to Add Owner to check checkboxes...")
        await page.goto('http://127.0.0.1:5000/add_owner')
        await asyncio.sleep(1)
        await page.screenshot(path='/home/jules/verification/add_owner_form.png', full_page=True)

        print("Navigating back to dashboard...")
        await page.goto('http://127.0.0.1:5000/')
        await asyncio.sleep(1)

        print("Accepting any alerts automatically")
        page.on("dialog", lambda dialog: print("Dialog message:", dialog.message) or dialog.accept())

        # Test clicking a toggle
        print("Trying to click a toggle btn...")
        try:
            await page.click('.toggle-btn.ready')
            print("Successfully clicked toggle!")
            await asyncio.sleep(1) # Wait for fetch call and UI update
            await page.screenshot(path='/home/jules/verification/dashboard_toggled.png', full_page=True)
        except Exception as e:
            print("Failed to click toggle btn:", e)

        await browser.close()

asyncio.run(run())
