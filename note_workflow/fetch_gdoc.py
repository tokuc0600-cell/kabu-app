"""Google DocsのテキストをDrive/Docs API経由で取得し、標準出力に返す（読み取り専用）。

使い方:
    uv run python note_workflow/fetch_gdoc.py [Google DocsのファイルID]
"""

import sys

from dotenv import load_dotenv
from google.auth.exceptions import DefaultCredentialsError
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/documents.readonly"]


def extract_text(document: dict) -> str:
    text = ""
    for element in document.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        for run in paragraph.get("elements", []):
            text_run = run.get("textRun")
            if text_run:
                text += text_run.get("content", "")
    return text


def fetch_document_text(document_id: str) -> str:
    import os

    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path:
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS が設定されていません（.envを確認してください）"
        )

    credentials = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=SCOPES
    )
    service = build("docs", "v1", credentials=credentials)
    document = service.documents().get(documentId=document_id).execute()
    return extract_text(document)


def main() -> None:
    load_dotenv()

    if len(sys.argv) != 2:
        print("使い方: python note_workflow/fetch_gdoc.py [Google DocsのファイルID]", file=sys.stderr)
        sys.exit(1)

    document_id = sys.argv[1]

    try:
        text = fetch_document_text(document_id)
    except FileNotFoundError:
        print(
            "エラー: サービスアカウントの認証情報ファイルが見つかりません。"
            " GOOGLE_APPLICATION_CREDENTIALS のパスを確認してください。",
            file=sys.stderr,
        )
        sys.exit(1)
    except DefaultCredentialsError:
        print(
            "エラー: Google認証情報の読み込みに失敗しました。"
            " .env の GOOGLE_APPLICATION_CREDENTIALS とJSONキーファイルの内容を確認してください。",
            file=sys.stderr,
        )
        sys.exit(1)
    except HttpError as e:
        if e.resp.status == 404:
            print(
                f"エラー: 指定されたファイルが見つかりません（ID: {document_id}）。"
                " ファイルIDが正しいか確認してください。",
                file=sys.stderr,
            )
        elif e.resp.status == 403:
            print(
                f"エラー: ファイルへのアクセス権限がありません（ID: {document_id}）。"
                " サービスアカウントとファイルが共有されているか確認してください。",
                file=sys.stderr,
            )
        else:
            print(f"エラー: Google APIの呼び出しに失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    print(text)


if __name__ == "__main__":
    main()
