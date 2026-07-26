package example;

final class InternalProjectNebulaSecretConfig {
    // openai chat/completions: this clue must not survive sensitive-content filtering.
    private static final String TOKEN = "FAKE_SCANNER_TOKEN_VALUE";
}
