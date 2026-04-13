import base64
import json
from typing import Any

import httpx

from ..schemas import MenuScanItem, NearbyRestaurant, NearbyRestaurantsRequest


def _fallback_restaurants(payload: NearbyRestaurantsRequest) -> list[NearbyRestaurant]:
    base_label = (payload.query or 'Current area').strip() or 'Current area'
    return [
        NearbyRestaurant(
            id='fallback-1',
            name='Maple & Thyme',
            address=f'{base_label}, 14 King Street',
            rating=4.7,
            reviewCount=428,
            distanceMeters=420,
            priceLevel='$$',
            openNow=True,
            primaryType='American',
            editorialSummary='Reliable comfort food with fast lunch service.',
        ),
        NearbyRestaurant(
            id='fallback-2',
            name='Paper Lantern',
            address=f'{base_label}, 201 Grant Ave',
            rating=4.6,
            reviewCount=311,
            distanceMeters=760,
            priceLevel='$$',
            openNow=True,
            primaryType='Asian',
            editorialSummary='Popular for noodle bowls and weeknight dinner picks.',
        ),
        NearbyRestaurant(
            id='fallback-3',
            name='Harvest Table',
            address=f'{base_label}, 88 Market Lane',
            rating=4.5,
            reviewCount=197,
            distanceMeters=980,
            priceLevel='$$',
            openNow=False,
            primaryType='Healthy',
            editorialSummary='Balanced bowls and lighter plates with strong dietary flexibility.',
        ),
    ]


def _text_from(value: Any, key: str = 'text') -> str | None:
    if isinstance(value, dict):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _normalize_place(place: dict[str, Any]) -> NearbyRestaurant:
    photos = place.get('photos') or []
    image_url = None
    if isinstance(photos, list) and photos:
        first_photo = photos[0]
        if isinstance(first_photo, dict):
            image_url = first_photo.get('googleMapsUri') or first_photo.get('name')

    return NearbyRestaurant(
        id=str(place.get('id') or place.get('name') or ''),
        name=_text_from(place.get('displayName')) or 'Restaurant',
        address=str(place.get('formattedAddress') or place.get('shortFormattedAddress') or '').strip(),
        rating=place.get('rating'),
        reviewCount=place.get('userRatingCount'),
        distanceMeters=place.get('distanceMeters'),
        priceLevel=place.get('priceLevel'),
        openNow=(
            (place.get('currentOpeningHours') or {}).get('openNow')
            if isinstance(place.get('currentOpeningHours'), dict)
            else None
        ),
        primaryType=_text_from(place.get('primaryTypeDisplayName')) or place.get('primaryType'),
        imageUrl=image_url,
        editorialSummary=_text_from(place.get('editorialSummary')),
    )


async def search_nearby_restaurants(
    payload: NearbyRestaurantsRequest,
    api_key: str,
) -> tuple[list[NearbyRestaurant], str]:
    if not api_key:
        return _fallback_restaurants(payload), 'fallback'

    field_mask = ','.join(
        [
            'places.id',
            'places.displayName',
            'places.formattedAddress',
            'places.shortFormattedAddress',
            'places.rating',
            'places.userRatingCount',
            'places.priceLevel',
            'places.currentOpeningHours.openNow',
            'places.primaryType',
            'places.primaryTypeDisplayName',
            'places.editorialSummary',
            'places.photos',
            'places.distanceMeters',
        ]
    )

    headers = {
        'X-Goog-Api-Key': api_key,
        'X-Goog-FieldMask': field_mask,
        'Content-Type': 'application/json',
    }

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            if payload.kind == 'coordinates' and payload.latitude is not None and payload.longitude is not None:
                response = await client.post(
                    'https://places.googleapis.com/v1/places:searchNearby',
                    headers=headers,
                    json={
                        'includedTypes': ['restaurant'],
                        'maxResultCount': 10,
                        'rankPreference': 'DISTANCE',
                        'locationRestriction': {
                            'circle': {
                                'center': {
                                    'latitude': payload.latitude,
                                    'longitude': payload.longitude,
                                },
                                'radius': float(payload.radius_meters or 2400),
                            }
                        },
                    },
                )
            else:
                response = await client.post(
                    'https://places.googleapis.com/v1/places:searchText',
                    headers=headers,
                    json={
                        'textQuery': f"restaurants near {payload.query or 'current area'}",
                        'maxResultCount': 10,
                    },
                )

            response.raise_for_status()
            body = response.json()
            places = body.get('places') or []
            normalized = [_normalize_place(place) for place in places if isinstance(place, dict)]
            if normalized:
                return normalized, 'google_places'
    except Exception:
        pass

    return _fallback_restaurants(payload), 'fallback'


def _fallback_menu_items(restrictions: list[str]) -> list[MenuScanItem]:
    lower = {item.lower() for item in restrictions}
    avoid_dairy = any('dairy' in item or 'milk' in item for item in lower)
    return [
        MenuScanItem(
            name='Grilled Salmon Bowl',
            description='Citrus rice, greens, pickled cucumber',
            price='$18',
            recommendation='best',
            reason='High-protein, balanced, and closest to your usual lighter comfort picks.',
        ),
        MenuScanItem(
            name='Roasted Chicken Plate',
            description='Herb potatoes, seasonal vegetables',
            price='$17',
            recommendation='safe',
            reason='A steady option with broad appeal and low dietary risk.',
        ),
        MenuScanItem(
            name='Creamy Truffle Pasta',
            description='Parmesan cream, mushrooms, butter sauce',
            price='$21',
            recommendation='avoid' if avoid_dairy else 'safe',
            reason=(
                'Likely rich and dairy-heavy, so it is less aligned with your profile.'
                if avoid_dairy
                else 'Heavier than your usual picks, but still workable if you want a treat.'
            ),
            caution='Contains dairy' if avoid_dairy else 'Richer than your usual choices',
        ),
    ]


async def scan_menu_image(
    *,
    file_bytes: bytes,
    filename: str,
    cuisines: list[str],
    restrictions: list[str],
    restaurant_name: str | None,
    openai_api_key: str,
) -> tuple[list[MenuScanItem], str, str | None]:
    if not openai_api_key:
        return (
            _fallback_menu_items(restrictions),
            'fallback',
            'Menu scan is using the built-in fallback because AI extraction is not configured.',
        )

    mime = 'image/jpeg'
    lower_name = filename.lower()
    if lower_name.endswith('.png'):
        mime = 'image/png'
    elif lower_name.endswith('.webp'):
        mime = 'image/webp'

    b64 = base64.b64encode(file_bytes).decode('ascii')
    prompt = (
        'Extract menu items from this restaurant menu image and recommend dishes for a user. '
        'Return strict JSON with a top-level object: '
        '{"items":[{"name":"","description":"","price":"","recommendation":"best|safe|avoid","reason":"","caution":""}]}. '
        f'User cuisines: {", ".join(cuisines) or "unknown"}. '
        f'User dietary restrictions: {", ".join(restrictions) or "none"}. '
        f'Restaurant name: {restaurant_name or "unknown"}. '
        'Choose at most 8 items. Use "avoid" when a dish likely conflicts with restrictions.'
    )

    body = {
        'model': 'gpt-4.1-mini',
        'input': [
            {
                'role': 'user',
                'content': [
                    {'type': 'input_text', 'text': prompt},
                    {'type': 'input_image', 'image_url': f'data:{mime};base64,{b64}'},
                ],
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                'https://api.openai.com/v1/responses',
                headers={
                    'Authorization': f'Bearer {openai_api_key}',
                    'Content-Type': 'application/json',
                },
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
            output_text = ''
            for item in payload.get('output', []):
                if item.get('type') == 'message':
                    for content in item.get('content', []):
                        if content.get('type') == 'output_text':
                            output_text += content.get('text', '')
            parsed = json.loads(output_text)
            items = parsed.get('items') if isinstance(parsed, dict) else None
            normalized: list[MenuScanItem] = []
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    recommendation = str(item.get('recommendation') or 'safe')
                    if recommendation not in {'best', 'safe', 'avoid'}:
                        recommendation = 'safe'
                    name = str(item.get('name') or '').strip()
                    reason = str(item.get('reason') or '').strip()
                    if not name or not reason:
                        continue
                    normalized.append(
                        MenuScanItem(
                            name=name,
                            description=str(item.get('description') or '').strip() or None,
                            price=str(item.get('price') or '').strip() or None,
                            recommendation=recommendation,
                            reason=reason,
                            caution=str(item.get('caution') or '').strip() or None,
                        )
                    )
            if normalized:
                return normalized, 'ai', None
    except Exception:
        pass

    return (
        _fallback_menu_items(restrictions),
        'fallback',
        'AI extraction was unavailable, so Teller returned a safe fallback read.',
    )
