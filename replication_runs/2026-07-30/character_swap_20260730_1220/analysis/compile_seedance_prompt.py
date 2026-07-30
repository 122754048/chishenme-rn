import hashlib
import json
import sys
from pathlib import Path


RUN = Path(__file__).resolve().parents[1]
SKILL_ROOT = Path(r'C:\Users\zhaocx04\.codex\skills\universal-source-fidelity-replication')
SEEDANCE_ROOT = Path(r'C:\Users\zhaocx04\.codex\skills\seedance-20')
sys.path.insert(0, str(SKILL_ROOT / 'scripts'))

from line_contract import normalize_text, rebind_line_contracts, render_line_for_prompt
from seedance_prompt_compiler import _format_segment, compile_prompt, derive_compiler_checks, validate_compiled_prompt


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha(value: object) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))


def file_sha(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def line(line_id: str, cut_id: str, start_ms: int, end_ms: int, exact: str, speaker_id: str, role: str, visibility: str) -> dict:
    return {
        'line_id': line_id,
        'cut_id': cut_id,
        'speaker': {
            'id': speaker_id,
            'role': role,
            'visibility': visibility,
            'voice_policy': 'natural unbranded Japanese adult dialogue; no voice imitation',
        },
        'language': {'bcp47': 'ja-JP', 'script': 'Jpan'},
        'time': {
            'start_ms': start_ms,
            'end_ms': end_ms,
            'duration_ms': end_ms - start_ms,
            'duration_is_derived': True,
            'time_base': 'output_global_ms',
            'cut_ids': [cut_id],
            'cross_cut_reason': None,
            'planned_safe_margin_ms': 0,
        },
        'text': {'exact': exact, 'normalized': normalize_text(exact).lower(), 'pronunciation_notes': []},
        'delivery': {
            'tone': 'casual',
            'pace': 'source timing',
            'volume': 'close mic',
            'breath': 'natural',
            'mic_distance': 'close',
            'accent_or_locale': 'ja-JP',
            'emphasis': [],
        },
        'lip_sync': {
            'priority': 'medium' if visibility == 'off_camera' else 'high',
            'face_visibility': 'off-camera' if visibility == 'off_camera' else 'face visible',
            'occlusion': 'none',
            'head_motion_limit': 'small only',
            'articulation': 'Japanese',
            'speaker_face_ref': 'approved character reference for the on-camera interviewee' if visibility == 'on_camera' else 'off-camera interviewer',
            'allowed_tolerance_ms': 120,
        },
        'proof_events': [],
        'foley_events': [],
        'silence_windows': [],
        'music_policy': {'mode': 'none', 'windows': []},
        'claim_ids': [],
        'qc_contract': {
            'asr_profile': 'ja-JP exact-line comparison',
            'speaker_check': 'single assigned speaker per line',
            'language_check': 'Japanese Jpan',
            'line_tolerance_ms': 120,
            'proof_sync_tolerance_ms': 120,
            'foley_sync_tolerance_ms': 120,
            'hard_fail_flags': ['wrong speaker', 'missing line', 'wrong language', 'background music'],
        },
        'criticality': 'H',
    }


def shot(shot_id: str, start_ms: int, end_ms: int, action: str, performance: str, endpoint: str, audio: str) -> dict:
    return {
        'shot_id': shot_id,
        'shot_scale': 'vertical medium-full handheld interview framing',
        'start_ms': start_ms,
        'end_ms': end_ms,
        'scene': 'Same night street and microphone.',
        'camera': 'Locked 9:16, tiny sway.',
        'lighting': 'Warm left, cool night.',
        'performance': performance,
        'action': action,
        'endpoint': endpoint,
        'product_or_ui_truth': 'No product; white top and dark skirt.',
        'commercial_proof': 'Interview reaction only.',
        'transition': 'Continuous.',
        'continuity': 'Same @Image2 woman and microphone.',
        'audio': audio,
        'factor_ids': [
            'S01.' + shot_id + '.scene',
            'S01.' + shot_id + '.camera',
            'S01.' + shot_id + '.lighting',
            'S01.' + shot_id + '.performance',
            'S01.' + shot_id + '.action',
            'S01.' + shot_id + '.audio',
        ],
    }


def main() -> None:
    plan = json.loads((RUN / 'analysis' / 'segment_plan.json').read_text(encoding='utf-8'))
    segment_plan = plan['segments'][0]
    lines = [
        line('L01', 'C01', 0, 1620, '今話題の「SUGO」知ってる？', 'interviewer', 'off-camera interviewer', 'off_camera'),
        line('L02', 'C02', 1620, 4500, 'もちろん！私も沼ってるよ！', 'interviewee', 'adult interviewee', 'on_camera'),
        line('L03', 'C03', 4500, 6000, 'ぶっちゃけどう？', 'interviewee', 'adult interviewee', 'on_camera'),
        line('L04', 'C04', 6000, 10660, '毎日刺激的すぎて正直ヤバい', 'interviewee', 'adult interviewee', 'on_camera'),
    ]
    lines[3]['time']['cut_ids'] = ['C04', 'C05']
    lines[3]['time']['cross_cut_reason'] = 'The approved closing line continues continuously across the subtitle-phase boundary.'
    lines = rebind_line_contracts(lines, plan['segments'])
    segment = {
        'segment_id': segment_plan['segment_id'],
        'start_ms': segment_plan['start_ms'],
        'end_ms': segment_plan['end_ms'],
        'output_global_start_ms': segment_plan['start_ms'],
        'duration_ms': segment_plan['duration_ms'],
        'cut_ids': segment_plan['cut_ids'],
        'opening_state': 'Attentive woman; mic lower left.',
        'reference_roles': [
            {'slot': 1, 'tag': '@Image1', 'role': 'approved five-Cut board: night street, camera, wardrobe and microphone'},
            {'slot': 2, 'tag': '@Image2', 'role': 'replacement woman face and dark straight-bang hair'},
        ],
        'locks': [
            '@Image1 locks Cut order, camera, wardrobe and microphone.',
            '@Image2 locks face and bangs.',
            'Video reference controls timing and blocking, never identity.',
            'Keep microphone at lower left and hands simple.',
            'Keep Japanese timing; no music.',
        ],
        'negative_constraints': [
            'No captions, graphics, text, logos, watermark or card.',
            'No extra people, product, prop, location change, cut or identity drift.',
            'No malformed hands, face change or exaggerated expression.',
        ],
        'shots': [
            shot('C01', 0, 1620, 'Interviewer asks; woman makes one small eye and head adjustment toward mic.', 'Attentive, mouth relaxed.', 'Faces camera-left, ready to answer.', 'L01 off-camera Japanese; night ambience; no music.'),
            shot('C02', 1620, 4500, 'Woman answers with a soft smile and one small shoulder response.', 'Small smile; steady face for lip sync.', 'Open smile; pose unchanged.', 'L02 on-camera Japanese; night ambience; no music.'),
            shot('C03', 4500, 6000, 'Woman gives one subtle head tilt for the setup line.', 'Small smile; no gesture.', 'Upright with same mic and eye line.', 'L03 on-camera Japanese; night ambience; no music.'),
            shot('C04', 6000, 8750, 'Woman speaks with contained smile and slight turn toward lens.', 'Small head turn; clear mouth.', 'Line continues without pose reset.', 'First L04 Japanese; night ambience; no music.'),
            shot('C05', 8750, 10867, 'Woman closes with light smile; hands meet before skirt; mic lowers.', 'Simple hands; steady face.', 'Smiling hands-together end; no freeze or card.', 'Final L04 Japanese; night ambience; no music.'),
        ],
        'no_speech_contracts': [],
    }
    factors = {'camera': True, 'motion': True, 'lighting': True, 'characters': True, 'audio': True}
    skill_files = {
        'seedance-20': SEEDANCE_ROOT / 'SKILL.md',
        'seedance-prompt': SEEDANCE_ROOT / 'skills' / 'seedance-prompt' / 'SKILL.md',
        'seedance-antislop': SEEDANCE_ROOT / 'skills' / 'seedance-antislop' / 'SKILL.md',
        'seedance-camera': SEEDANCE_ROOT / 'skills' / 'seedance-camera' / 'SKILL.md',
        'seedance-motion': SEEDANCE_ROOT / 'skills' / 'seedance-motion' / 'SKILL.md',
        'seedance-lighting': SEEDANCE_ROOT / 'skills' / 'seedance-lighting' / 'SKILL.md',
        'seedance-characters': SEEDANCE_ROOT / 'skills' / 'seedance-characters' / 'SKILL.md',
        'seedance-audio': SEEDANCE_ROOT / 'skills' / 'seedance-audio' / 'SKILL.md',
    }
    candidate = ' '.join(['Segment S01.', 'Reference @Image1.', 'Reference @Image2.'] + [render_line_for_prompt(item) for item in lines])
    checks = derive_compiler_checks(segment=segment, canonical_lines=lines, factors=factors, prompt=candidate, skill_files=skill_files)
    debug_prompt = ' '.join(_format_segment(segment) + [render_line_for_prompt(item) for item in lines])
    (RUN / 'seedance' / 'S01').mkdir(parents=True, exist_ok=True)
    (RUN / 'seedance' / 'S01' / 'compiled_prompt_debug.txt').write_text(debug_prompt, encoding='utf-8')
    print(len(debug_prompt))
    artifact = compile_prompt(segment=segment, line_contracts=lines, factors=factors, skill_files=skill_files, compiler_checks=checks)
    validate_compiled_prompt(artifact, skill_files=skill_files, line_contracts=lines)
    seedance_dir = RUN / 'seedance' / 'S01'
    seedance_dir.mkdir(parents=True, exist_ok=True)
    (seedance_dir / 'compiled_prompt.txt').write_text(artifact['prompt'] + '\n', encoding='utf-8')
    (seedance_dir / 'compiled_prompt.json').write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    input_contract = {
        'schema_version': 'usfr-seedance-input-contract/v1',
        'approved_script_sha256': file_sha(RUN / 'analysis' / 'reverse_storyboard_script.md'),
        'approved_storyboard_sha256': file_sha(RUN / 'storyboards' / 'segment_01_v1.png'),
        'approved_storyboard_meta_sha256': file_sha(RUN / 'storyboards' / 'segment_01_v1.meta.json'),
        'segment_plan_sha256': canonical_sha(plan),
        'compiled_prompt_sha256': sha256_bytes(artifact['prompt'].encode('utf-8')),
        'compiled_artifact_sha256': artifact['compiler']['output_sha256'],
        'reference_map': {
            'image_slot_1': 'storyboards/segment_01_v1.png',
            'image_slot_2': 'inputs/new_model_image.jpg',
            'video_slot_1': 'inputs/source_video.mp4 sliced to S01 only',
        },
        'target_change': 'new_model_image identity replacement',
        'provider': {'model': 'seedance-2.0-fast-token', 'resolution': '720p', 'ratio': '9:16', 'duration_ms': 10867, 'generateAudio': True, 'realPersonMode': True, 'conversionSlots': ['all']},
    }
    (seedance_dir / 'seedance_input_contract.json').write_text(json.dumps(input_contract, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
