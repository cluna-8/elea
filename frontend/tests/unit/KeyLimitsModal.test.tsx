// 057: la consola deja editar rpm/tpm de una llave existente (antes solo se fijaban al crearla).
// El modal valida lo mismo que el alta (rpm 1–10 000, tpm 1 000–10 000 000), manda solo lo que cambió y
// muestra el error del servidor (p. ej. el 503 «el motor no responde, los límites no se cambiaron») sin cerrarse.
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { KeyLimitsModal } from '../../src/components/KeyLimitsModal';

const base = { keyName: 'Kit claude_desktop', rpm: 60, tpm: 100000 };

describe('KeyLimitsModal', () => {
  it('muestra los límites actuales de la llave', () => {
    render(<KeyLimitsModal {...base} onSave={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText(/Kit claude_desktop/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Límite RPM/i)).toHaveValue(60);
    expect(screen.getByLabelText(/Límite TPM/i)).toHaveValue(100000);
  });

  it('guarda los dos límites nuevos', async () => {
    const onSave = vi.fn(async () => {});
    render(<KeyLimitsModal {...base} onSave={onSave} onClose={vi.fn()} />);
    const user = userEvent.setup();
    const rpm = screen.getByLabelText(/Límite RPM/i);
    const tpm = screen.getByLabelText(/Límite TPM/i);
    await user.clear(rpm); await user.type(rpm, '120');
    await user.clear(tpm); await user.type(tpm, '1000000');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(onSave).toHaveBeenCalledWith({ rpm_limit: 120, tpm_limit: 1000000 });
  });

  it('manda solo el campo que cambió', async () => {
    const onSave = vi.fn(async () => {});
    render(<KeyLimitsModal {...base} onSave={onSave} onClose={vi.fn()} />);
    const user = userEvent.setup();
    const tpm = screen.getByLabelText(/Límite TPM/i);
    await user.clear(tpm); await user.type(tpm, '1000000');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(onSave).toHaveBeenCalledWith({ tpm_limit: 1000000 });
  });

  it('sin cambios no llama al servidor', async () => {
    const onSave = vi.fn(async () => {});
    render(<KeyLimitsModal {...base} onSave={onSave} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it.each([['0', /Límite RPM/i], ['10001', /Límite RPM/i], ['999', /Límite TPM/i], ['10000001', /Límite TPM/i]])(
    'rechaza %s fuera de rango sin llamar al servidor', async (valor, etiqueta) => {
      const onSave = vi.fn(async () => {});
      render(<KeyLimitsModal {...base} onSave={onSave} onClose={vi.fn()} />);
      const user = userEvent.setup();
      const campo = screen.getByLabelText(etiqueta);
      await user.clear(campo); await user.type(campo, valor);
      await user.click(screen.getByRole('button', { name: 'Guardar' }));
      expect(onSave).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

  it('un error del servidor se muestra y el modal sigue abierto', async () => {
    const onClose = vi.fn();
    const onSave = vi.fn(async () => { throw new Error('El motor no responde. Los límites no se cambiaron.'); });
    render(<KeyLimitsModal {...base} onSave={onSave} onClose={onClose} />);
    const user = userEvent.setup();
    const rpm = screen.getByLabelText(/Límite RPM/i);
    await user.clear(rpm); await user.type(rpm, '120');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(await screen.findByText('El motor no responde. Los límites no se cambiaron.')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('cancelar cierra sin guardar', async () => {
    const onClose = vi.fn();
    const onSave = vi.fn();
    render(<KeyLimitsModal {...base} onSave={onSave} onClose={onClose} />);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(onClose).toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });
});
