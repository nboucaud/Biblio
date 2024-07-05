import { render } from 'preact';

import CreateGroupForm from './components/CreateGroupForm';
import readConfig from './config';

function init() {
  const shadowHost = document.querySelector('#create-group-form')!;
  const shadowRoot = shadowHost.attachShadow({ mode: 'open' });
  const config = readConfig();
  const stylesheetLinks = config.styles.map(stylesheetURL => (
    <link rel="stylesheet" href={stylesheetURL} />
  ));
  render(
    <>
      {stylesheetLinks}
      <CreateGroupForm />
    </>,
    shadowRoot,
  );
}

init();
