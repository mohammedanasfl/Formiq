import { Platform } from 'react-native';

// The backend's address. Set EXPO_PUBLIC_API_URL to use another one (a device on the same network
// needs the computer's address). The defaults are the dev server of backend/README.md, port 8000:
// an Android emulator reaches the computer at 10.0.2.2, everything else at localhost.
const configured = process.env.EXPO_PUBLIC_API_URL?.trim();
const fallback = Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://localhost:8000';

export const API_BASE_URL = (configured ? configured : fallback).replace(/\/+$/, '');
