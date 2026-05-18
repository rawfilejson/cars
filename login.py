import asyncio
from playwright.async_api import async_playwright

AUTH_FILE = 'auth.json'


async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir='./chrome_profile',
            headless=False,
            channel='chrome',
        )
        page = await context.new_page()

        await page.goto('https://auth.tnet.ge/ka/user/login/?Continue=https%3A%2F%2Fmyauto.ge%2Fka')

        print('Browser is open. Log in with Gmail (or any method).')
        print('When you are fully logged in and see your account, press Enter here...')
        await asyncio.get_event_loop().run_in_executor(None, input)

        await context.storage_state(path=AUTH_FILE)
        print(f'Session saved to {AUTH_FILE}')
        print('You can now run MyAuto.py — it will use this session automatically.')
        await context.close()


asyncio.run(main())
