import * as ImagePicker from 'expo-image-picker';
import { backendApi, type MenuScanItem } from '../api/backend';

type PickerSource = 'camera' | 'library';

async function ensurePermissions(source: PickerSource) {
  if (source === 'camera') {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    return permission.granted;
  }
  const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
  return permission.granted;
}

async function pickImage(source: PickerSource) {
  const granted = await ensurePermissions(source);
  if (!granted) {
    throw new Error(source === 'camera' ? 'Camera access was denied.' : 'Photo library access was denied.');
  }

  const result =
    source === 'camera'
      ? await ImagePicker.launchCameraAsync({
          allowsEditing: false,
          quality: 0.8,
          mediaTypes: ['images'],
        })
      : await ImagePicker.launchImageLibraryAsync({
          allowsEditing: false,
          quality: 0.8,
          mediaTypes: ['images'],
        });

  if (result.canceled || result.assets.length === 0) {
    return null;
  }

  return result.assets[0];
}

export const menuScanService = {
  async scanFromSource(
    token: string,
    source: PickerSource,
    payload: { cuisines: string[]; restrictions: string[]; restaurantName?: string | null }
  ): Promise<{ items: MenuScanItem[]; source: 'ai' | 'fallback'; note?: string | null }> {
    const asset = await pickImage(source);
    if (!asset?.uri) {
      throw new Error('No menu image was selected.');
    }

    const filename = asset.fileName || `menu-scan.${asset.mimeType?.split('/')[1] || 'jpg'}`;
    const form = new FormData();
    form.append('file', {
      uri: asset.uri,
      name: filename,
      type: asset.mimeType || 'image/jpeg',
    } as unknown as Blob);
    form.append('cuisines', JSON.stringify(payload.cuisines));
    form.append('restrictions', JSON.stringify(payload.restrictions));
    if (payload.restaurantName) {
      form.append('restaurant_name', payload.restaurantName);
    }

    return backendApi.scanMenu(token, form);
  },
};
