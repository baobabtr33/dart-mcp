# Getting a free OpenDART API key (English walkthrough)

The OpenDART site is only in Korean, but signing up takes about 2 minutes. The key is free
and allows 20,000 requests per day.

> Tip: right-click the page in Chrome and choose **Translate to English**. The Korean labels
> below are what you'll see if you don't translate.

1. Go to **https://opendart.fss.or.kr**.
2. In the top menu, open **인증키 신청/관리** (API key application / management) and
   choose **인증키 신청** (apply for an API key).
3. Choose **개인** (individual), unless you are registering for a company.
4. Fill in the form:
   - **이메일**: email (this is your login ID)
   - **비밀번호**: password
   - **사용용도**: purpose of use. Something like "Investment research" is fine.
   - Agree to the terms (**동의**) and submit.
5. Open the verification email from OpenDART and click the link.
6. Log in, then go to **인증키 신청/관리 → 오픈API 이용현황** (API usage status). Your key
   is the 40-character string shown there.
7. Pass the key to the server as `DART_API_KEY`:

   ```bash
   claude mcp add dart -e DART_API_KEY=your_40_char_key -- uvx korea-dart-mcp
   ```

## Troubleshooting

| Error from the server | Meaning | Fix |
|---|---|---|
| `DART error 010: Unregistered API key` | Typo, or email not verified yet | Copy the key again and check the verification email |
| `DART error 011: API key is not usable` | Key suspended | Check the notices on opendart.fss.or.kr |
| `DART error 012: Access from this IP is not allowed` | IP restriction on the key | Remove the IP restriction in the key settings |
| `DART error 020: Daily request limit exceeded` | Used 20,000 calls today | Wait until midnight KST, or use a second key |
| `DART error 901: API key expired` | Account retention period passed | Log in and renew, or apply again |

If the menu layout has changed, use the translated page and look for "API key" or "인증키".
Please open an issue so this guide can be updated.
