import axios from 'axios';

const client = axios.create({
  baseURL: 'http://127.0.0.1:8765/api',
  timeout: 15000,
});

export default client;
