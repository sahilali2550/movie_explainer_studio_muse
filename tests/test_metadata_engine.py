import pytest
from app.services.metadata_engine import MetadataEngine

def test_metadata_engine_all_genres():
    """Verify that MetadataEngine correctly generates metadata across all supported genres."""
    genres = ["movie_recap", "biography", "documentary", "true_crime", "tech_science", "video_essay"]
    for g in genres:
        result = MetadataEngine.generate_viral_metadata(
            movie_title="Inception",
            script_snippet="A thief who steals corporate secrets through dream-sharing technology...",
            lang="en",
            genre=g
        )
        assert result["movie_title"] == "Inception"
        assert result["genre"] == g
        assert isinstance(result["titles"], list)
        assert len(result["titles"]) == 3
        assert "Inception" in result["description"]
        assert "COPYRIGHT & FAIR USE DISCLAIMER" in result["description"]
        assert isinstance(result["tags"], list)
        assert len(result["tags"]) > 0
        assert isinstance(result["hashtags"], list)
        assert len(result["hashtags"]) > 0
        assert isinstance(result["pinned_comment"], str)
        assert len(result["pinned_comment"]) > 0


def test_metadata_engine_multilingual_support():
    """Verify that MetadataEngine properly personalizes metadata for all supported languages."""
    languages = ["en", "ur", "hi", "es", "id", "ar"]
    for lang in languages:
        result = MetadataEngine.generate_viral_metadata(
            movie_title="Interstellar",
            script_snippet="A team of explorers travel through a wormhole in space...",
            lang=lang,
            genre="movie_recap"
        )
        assert len(result["titles"]) == 3
        assert len(result["tags"]) >= 4
        assert len(result["hashtags"]) >= 3
        assert "Interstellar" in result["description"]
        if lang in ["ur", "hi"]:
            assert any("کہانی" in t or "دھوکہ" in t or "قاتل" in t for t in result["titles"])
        elif lang == "es":
            assert any("SECRETO" in t or "final" in t for t in result["titles"])
        elif lang == "id":
            assert any("RAHASIA" in t or "Alur Cerita" in t for t in result["titles"])
        elif lang == "ar":
            assert any("قصة" in t or "فيلم" in t for t in result["titles"])


def test_metadata_engine_empty_or_default_title_fallback():
    """Verify that empty or generic default titles fall back to 'This Viral Story'."""
    result = MetadataEngine.generate_viral_metadata(
        movie_title="Movie Story Explanation",
        script_snippet="Sample snippet...",
        lang="en",
        genre="movie_recap"
    )
    assert result["movie_title"] == "This Viral Story"
    assert any("This Viral Story" in t for t in result["titles"])

    result_empty = MetadataEngine.generate_viral_metadata(
        movie_title="   ",
        script_snippet="Sample snippet...",
        lang="en",
        genre="movie_recap"
    )
    assert result_empty["movie_title"] == "This Viral Story"


def test_metadata_engine_biography_and_true_crime_urdu():
    """Verify localized outputs for biography and true_crime genres in Urdu."""
    bio_res = MetadataEngine.generate_viral_metadata(
        movie_title="Allama Iqbal",
        script_snippet="Life story...",
        lang="ur",
        genre="biography"
    )
    assert any("داستان" in t or "بایوگرافی" in t for t in bio_res["titles"])
    assert "#Biography" in bio_res["hashtags"]

    crime_res = MetadataEngine.generate_viral_metadata(
        movie_title="Zodiac Mystery",
        script_snippet="Crime scene investigation...",
        lang="ur",
        genre="true_crime"
    )
    assert any("سازش" in t or "خوفناک" in t for t in crime_res["titles"])
    assert "#TrueCrime" in crime_res["hashtags"]


def test_metadata_engine_clean_movie_title():
    """Verify that clean_movie_title strips spam keywords, release years, and pipes."""
    assert MetadataEngine.clean_movie_title("Sera The Untold | Hollywood Blockbuster Full Movie in Hindi Dubbed 2024 HD") == "Sera The Untold"
    assert MetadataEngine.clean_movie_title("Inception (2010) [1080p BluRay]") == "Inception"
    assert MetadataEngine.clean_movie_title("The Dark Knight - Official Trailer") == "The Dark Knight"
    assert MetadataEngine.clean_movie_title("Titanic") == "Titanic"
    assert MetadataEngine.clean_movie_title("KGF Chapter 2 | Full Hindi Movie 2022") == "KGF Chapter 2"
    assert MetadataEngine.clean_movie_title("") == "This Viral Story"

