# AI LLM Matrix Bot

AI LLM Matrix Bot is a chatbot for the [Matrix](https://matrix.org/) chat protocol, designed to interact with an XWiki LLM application (https://extensions.xwiki.org/xwiki/bin/view/Extension/LLM/).

This project is based on [nfinigpt-matrix](https://github.com/h1ddenpr0cess20/infinigpt-matrix/) by h1ddenpr0cess20, with significant modifications and enhancements to work with XWiki and custom AI models.

## Features

- Interacts with XWiki's RAG system for enhanced responses
- Supports multiple AI models, configurable through the XWiki interface
- Personalized chat history for each user in each channel
- Ability to assume different personalities or use custom prompts
- Collaborative feature allowing users to interact with each other's chat histories
- Configurable moderation system to filter inappropriate content
- Flexible JWT-based authentication for secure communication with the XWiki server

## Setup

1. Clone the repository:

```
git clone https://github.com/xwiki-contrib/ai-llm-matrix-bot.git
cd ai-llm-matrix-bot
```

2. Prepare the environment using conda:
```
conda env create -f environment.yml
```

and activate it

```
conda activate matrix-bot
```

3. Set up a [Matrix account](https://app.element.io/) for your bot.  You'll need the server, username and password.

4. Create a `config.json` file based on the provided template and fill in the necessary details:
- Matrix server information
- XWiki endpoint
- Bot credentials
- Allowed channels
- Admin users
- Default model and other configuration options


5. Generate an EdDSA key pair and save the private key as `private.pem` in the project directory.

```
openssl genpkey -algorithm ed25519 -outform PEM -out private.pem
openssl pkey -in private.pem -pubout -outform PEM -out public.pem
```

Plug those into the appropriate variables in the config.json file.

6. Configure the XWiki server to accept JWT tokens from the bot, using https://extensions.xwiki.org/xwiki/bin/view/Extension/LLM/Authenticator/

7. Run the bot:
```
python infinigpt.py
```
## Configuration

The `config.json` file contains all the necessary configuration options. Here are some key settings:

- `models`: List of allowed AI models
- `server`: Matrix server URL
- `xwiki_xwiki_v1_endpoint`: XWiki RAG system endpoint
- `matrix_username` and `matrix_password`: Bot's Matrix credentials
- `channels`: List of allowed Matrix channels
- `admins`: List of Matrix user IDs with admin privileges
- `default_model`: The default AI model to use
- `jwt_payload`: Custom claims for the JWT used in XWiki authentication
- `moderation_enabled` and `moderation_strategy`: Content moderation settings
- `forbidden_words`: List of words to be filtered in moderation

Refer to the comments in the `config.json` file for detailed explanations of each option.

## Usage

Users can interact with the bot using the following commands:

- `.ai <message>` or `@botname: <message>`: Send a message to the bot
- `.x <user> <message>`: Interact with another user's chat history
- `.persona <personality>`: Change the bot's personality
- `.custom <prompt>`: Use a custom system prompt
- `.reset`: Reset to the default personality
- `.stock`: Remove personality and reset to standard settings
- `.model`: List available AI models
- `.model <modelname>`: Change the current AI model
- `.model reset`: Reset to the default model
- `.help`: Display the help menu

## Development

This project is actively maintained by the XWiki community. Contributions, bug reports, and feature requests are welcome. Please submit issues and pull requests to the [GitHub repository](https://github.com/xwiki-contrib/ai-llm-matrix-bot).

## License

This project is licensed under [LGPL v2.1](https://www.gnu.org/licenses/lgpl-2.1.en.html).

## Acknowledgements

Special thanks to h1ddenpr0cess20 for the original [infinigpt-irc](https://github.com/h1ddenpr0cess20/infinigpt-irc/) project, which served as the foundation for this Matrix bot.

---

* Project Lead: Ludovic Dubost 
* [Issue Tracker](https://jira.xwiki.org/browse/LLMAI)
* Communication: [Forum](https://forum.xwiki.org/), [Chat](https://dev.xwiki.org/xwiki/bin/view/Community/Chat)
* License: LGPL 2.1
* Translations: N/A
* Sonar Dashboard: N/A
* Continuous Integration Status: N/A
