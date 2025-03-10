# HN Saver Bot

A simple Telegram bot to bookmark Hacker News stories and fetch comments using the HN API.

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/Amanuel94/hn-saver-bot.git
cd hn-saver-bot
npm install
```
## Configuration

Create a `.env` file in the project root with your credentials:

```
API_TOKEN = '<bot api token>'
WEBHOOK_URL = '<webhook url for deployment>' # for dev use localtunnel
WEBHOOK_ROUTE = <'webhook route'>                                                                 
DEVELOPMENT = <'True' OR 'False'>
MONGO_URL = "<remote mongo database url>"
CHANNEL_ID = "the channel you want hn-saver-bot to brodcast hn stories"
```

Enjoy!
