CREATE TABLE IF NOT EXISTS public.urls (
	id SERIAL NOT NULL,
    origin TEXT NOT NULL UNIQUE,
    alias TEXT NOT NULL UNIQUE,
    created_by BIGINT NOT NULL,

    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_origin_unique
    ON public.urls(origin);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alias_unique
    ON public.urls(alias);

--

CREATE TABLE IF NOT EXISTS public.users (
	id SERIAL NOT NULL,
    email TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT False,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),

    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_unique
    ON public.users(LOWER(email));

--

CREATE TABLE IF NOT EXISTS public.refresh_tokens (
    id SERIAL NOT NULL,
    owner_id BIGINT NOT NULL,
    refresh_token TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,

    FOREIGN KEY (owner_id)
        REFERENCES public.users(id)
            ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_owner_id
    ON public.refresh_tokens(owner_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_token
    ON public.refresh_tokens(refresh_token);

--
